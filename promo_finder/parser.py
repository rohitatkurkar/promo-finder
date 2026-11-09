"""Read screenplay files and turn them into cues with unique IDs.

A "cue" is one timed block in the screenplay: a line of dialogue, an action,
a camera direction or a sound description. Everything later in the pipeline
refers to cues by their ID (for example E06_C0012), so this file is the only
place where timestamps enter the system.

Nothing is silently thrown away. If something cannot be read, it is recorded
as an issue so it can be reported.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

DIALOGUE = "dialogue"
ACTION = "action"
CAMERA = "camera"
SOUND = "sound"

# Dialogue and action are events a viewer experiences. Camera and sound cues
# only describe how the event is shown, so they can never be a hook by themselves.
STORY_KINDS = (DIALOGUE, ACTION)

CUE_LABEL = re.compile(r"^\*\*(?P<label>.+?):\*\*\s*$")
CUE_TIME = re.compile(r"^Start:\s*\((?P<start>[^)]*)\)\s*\|\s*End:\s*\((?P<end>[^)]*)\)\s*$")
TIMESTAMP = re.compile(r"^(?P<minutes>\d{1,3}):(?P<seconds>\d{2}(?:\.\d{1,3})?)$")
SCENE_NUMBER = re.compile(r"^SCENE\s+(?P<number>\d+)\s*$", re.IGNORECASE)
SCENE_FIELD = re.compile(
    r"^(?P<name>scene heading|scene start|scene end|actions and dialogue)\s*:\s*(?P<value>.*)$",
    re.IGNORECASE,
)
HEADER_FIELD = re.compile(
    r"^(?P<name>EPISODE NUMBER|EPISODE LOGLINE|CONTINUITY NOTES)\s*:\s*(?P<value>.*)$"
)
EPISODE_NUMBER_IN_TEXT = re.compile(r"(\d+)")
EPISODE_NUMBER_IN_FILENAME = re.compile(r"episode[-_ ]?0*(\d+)", re.IGNORECASE)
PARENTHETICAL = re.compile(r"\(([^)]*)\)")

# Screenplay notes that say how a line is heard, not how it is acted.
VOICE_OVER = re.compile(r"\bV\.?\s*O\.?\b", re.IGNORECASE)
OFF_SCREEN = re.compile(r"\bO\.?\s*S\.?\b", re.IGNORECASE)

# Two cues on the same track may overlap by this much (seconds) before it is
# worth mentioning. Below this it is just rounding in the script.
OVERLAP_TOLERANCE = 0.05


class ScreenplayPackError(Exception):
    """The input pack itself cannot be used, for example a corrupted ZIP."""


@dataclass
class Cue:
    cue_id: str
    episode: int
    scene: int | None
    kind: str
    raw_label: str
    speaker: str | None
    delivery: str | None
    voice_mode: str | None
    start: float | None
    end: float | None
    text: str
    source_line: int
    issues: list[str] = field(default_factory=list)

    @property
    def has_valid_time(self) -> bool:
        return self.start is not None and self.end is not None and self.end > self.start

    @property
    def is_story_event(self) -> bool:
        return self.kind in STORY_KINDS


@dataclass
class Scene:
    number: int
    heading: str | None
    start: float | None
    end: float | None
    source_line: int
    issues: list[str] = field(default_factory=list)


@dataclass
class ParseIssue:
    """One problem found while reading a file."""

    episode: int | None
    file_name: str
    line: int | None
    issue_type: str
    detail: str
    cue_id: str | None = None


@dataclass
class Episode:
    number: int
    file_name: str
    logline: str
    continuity_notes: str
    scenes: list[Scene]
    cues: list[Cue]
    issues: list[ParseIssue]
    content_hash: str
    label_style: str

    @property
    def duration(self) -> float:
        """Last moment anything happens in the episode, from valid cues and scene ends."""
        times = [c.end for c in self.cues if c.has_valid_time]
        times += [s.end for s in self.scenes if s.end is not None]
        return max(times) if times else 0.0

    def cue(self, cue_id: str) -> Cue | None:
        for cue in self.cues:
            if cue.cue_id == cue_id:
                return cue
        return None


def parse_timestamp(value: str) -> float | None:
    """Convert '01:04.80' to 64.8 seconds. Return None if the text is not a valid time."""
    match = TIMESTAMP.match(value.strip())
    if not match:
        return None
    seconds = float(match.group("seconds"))
    if seconds >= 60:
        return None
    return round(int(match.group("minutes")) * 60 + seconds, 3)


def format_timestamp(seconds: float) -> str:
    """Convert 64.8 to '01:04.80', the format the screenplays use."""
    total_hundredths = int(round(seconds * 100))
    minutes, hundredths = divmod(total_hundredths, 6000)
    return f"{minutes:02d}:{hundredths / 100:05.2f}"


def split_label(raw_label: str) -> tuple[str, str | None, str | None, str | None]:
    """Split a cue label into (kind, speaker, delivery note, voice mode).

    'LADY ANNA (Confused, Breathless)' becomes dialogue spoken by 'LADY ANNA'.
    Different labels are deliberately NOT merged here: LADY ANNA, ANNA and
    THE OLD FRIEND stay as written, because the script alone does not prove
    that two labels are the same person.
    """
    label = raw_label.strip()
    upper = label.upper()
    if upper == "CAMERA" or upper.startswith("CAMERA "):
        return CAMERA, None, None, None
    if upper == "ACTION" or upper.startswith("ACTION "):
        return ACTION, None, None, None
    if upper.startswith("SOUND"):
        return SOUND, None, None, None

    notes = PARENTHETICAL.findall(label)
    speaker = PARENTHETICAL.sub("", label).strip(" :-")
    voice_mode = "on_screen"
    delivery_parts = []
    for note in notes:
        if VOICE_OVER.search(note):
            voice_mode = "voice_over"
        elif OFF_SCREEN.search(note):
            voice_mode = "off_screen"
        else:
            delivery_parts.append(note.strip())
    delivery = ", ".join(part for part in delivery_parts if part) or None
    return DIALOGUE, speaker, delivery, voice_mode


def clean_dialogue(text: str) -> str:
    """Remove the double quotes wrapping a dialogue line, keeping the words unchanged."""
    text = text.strip()
    if len(text) >= 2 and text[0] in "\"“" and text[-1] in "\"”":
        return text[1:-1].strip()
    return text


def episode_number_from_filename(file_name: str) -> int | None:
    match = EPISODE_NUMBER_IN_FILENAME.search(PurePosixPath(file_name).name)
    return int(match.group(1)) if match else None


def parse_episode_text(text: str, file_name: str = "<memory>") -> Episode:
    """Parse the text of one episode file. Problems become issues, not exceptions."""
    issues: list[ParseIssue] = []
    lines = text.splitlines()

    header: dict[str, str] = {}
    scenes: list[Scene] = []
    raw_cues: list[dict] = []
    current_scene: Scene | None = None
    saw_script_start = False
    saw_script_end = False
    title_case_labels = upper_case_labels = 0

    filename_number = episode_number_from_filename(file_name)

    index = 0
    while index < len(lines):
        line_number = index + 1
        line = lines[index].strip()
        index += 1
        if not line:
            continue

        header_match = HEADER_FIELD.match(line)
        if header_match and not saw_script_start:
            header[header_match.group("name")] = header_match.group("value").strip()
            continue
        if line.startswith("--- SCRIPT START"):
            saw_script_start = True
            continue
        if line.startswith("--- SCRIPT END"):
            saw_script_end = True
            continue

        scene_match = SCENE_NUMBER.match(line)
        if scene_match:
            current_scene = Scene(int(scene_match.group("number")), None, None, None, line_number)
            scenes.append(current_scene)
            continue

        field_match = SCENE_FIELD.match(line)
        if field_match:
            name = field_match.group("name")
            if name.isupper():
                upper_case_labels += 1
            else:
                title_case_labels += 1
            value = field_match.group("value").strip()
            key = name.lower()
            if key == "actions and dialogue":
                continue
            if current_scene is None:
                issues.append(ParseIssue(None, file_name, line_number, "scene_field_outside_scene", line))
                continue
            if key == "scene heading":
                current_scene.heading = value or None
            else:
                parsed = parse_timestamp(value)
                if parsed is None:
                    issues.append(
                        ParseIssue(None, file_name, line_number, "invalid_scene_time", f"{name}: {value!r}")
                    )
                elif key == "scene start":
                    current_scene.start = parsed
                else:
                    current_scene.end = parsed
            continue

        label_match = CUE_LABEL.match(line)
        if label_match:
            raw_label = label_match.group("label")
            time_line = None
            text_lines: list[str] = []
            # Read the block under the label until the next blank line or structural line.
            while index < len(lines):
                peek = lines[index].strip()
                if not peek:
                    break
                if CUE_LABEL.match(peek) or SCENE_NUMBER.match(peek) or peek.startswith("--- SCRIPT"):
                    break
                if time_line is None and CUE_TIME.match(peek):
                    time_line = peek
                else:
                    text_lines.append(peek)
                index += 1
            raw_cues.append(
                {
                    "raw_label": raw_label,
                    "time_line": time_line,
                    "text": " ".join(text_lines).strip(),
                    "scene": current_scene.number if current_scene else None,
                    "line": line_number,
                }
            )
            continue

        issues.append(ParseIssue(None, file_name, line_number, "unrecognised_line", line[:200]))

    # Decide the episode number, recording any disagreement between sources.
    header_number = None
    if "EPISODE NUMBER" in header:
        found = EPISODE_NUMBER_IN_TEXT.search(header["EPISODE NUMBER"])
        header_number = int(found.group(1)) if found else None
    if header_number is None and filename_number is None:
        issues.append(ParseIssue(None, file_name, None, "missing_episode_number", "No number in header or file name"))
    elif header_number is None:
        issues.append(ParseIssue(None, file_name, None, "missing_episode_number", "Header has no number, used file name"))
    elif filename_number is not None and header_number != filename_number:
        issues.append(
            ParseIssue(
                None, file_name, None, "episode_number_mismatch",
                f"Header says {header_number}, file name says {filename_number}. Header used.",
            )
        )
    number = header_number if header_number is not None else (filename_number or 0)

    for required in ("EPISODE LOGLINE", "CONTINUITY NOTES"):
        if required not in header:
            issues.append(ParseIssue(number, file_name, None, "missing_header_field", required))
    if not saw_script_start:
        issues.append(ParseIssue(number, file_name, None, "missing_script_marker", "SCRIPT START"))
    if not saw_script_end:
        issues.append(ParseIssue(number, file_name, None, "missing_script_marker", "SCRIPT END"))

    # Build the cues and give each one its permanent ID.
    cues: list[Cue] = []
    for position, raw in enumerate(raw_cues, start=1):
        cue_id = f"E{number:02d}_C{position:04d}"
        kind, speaker, delivery, voice_mode = split_label(raw["raw_label"])
        text_value = clean_dialogue(raw["text"]) if kind == DIALOGUE else raw["text"]
        cue = Cue(cue_id, number, raw["scene"], kind, raw["raw_label"], speaker, delivery, voice_mode,
                  None, None, text_value, raw["line"])

        if raw["time_line"] is None:
            cue.issues.append("missing_timestamp")
        else:
            time_match = CUE_TIME.match(raw["time_line"])
            start_text, end_text = time_match.group("start").strip(), time_match.group("end").strip()
            if not start_text:
                cue.issues.append("missing_start")
            else:
                cue.start = parse_timestamp(start_text)
                if cue.start is None:
                    cue.issues.append(f"invalid_start:{start_text}")
            if not end_text:
                cue.issues.append("missing_end")
            else:
                cue.end = parse_timestamp(end_text)
                if cue.end is None:
                    cue.issues.append(f"invalid_end:{end_text}")
            if cue.start is not None and cue.end is not None and cue.end <= cue.start:
                cue.issues.append("end_not_after_start")
        if not text_value:
            cue.issues.append("empty_text")
        if raw["scene"] is None:
            cue.issues.append("cue_outside_scene")
        cues.append(cue)

    label_style = "uppercase" if upper_case_labels and not title_case_labels else (
        "mixed" if upper_case_labels and title_case_labels else "titlecase"
    )

    episode = Episode(
        number=number,
        file_name=file_name,
        logline=header.get("EPISODE LOGLINE", ""),
        continuity_notes=header.get("CONTINUITY NOTES", ""),
        scenes=scenes,
        cues=cues,
        issues=issues,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        label_style=label_style,
    )
    for issue in issues:
        issue.episode = number
    _check_cue_quality(episode)
    return episode


def _check_cue_quality(episode: Episode) -> None:
    """Look for data problems. Each one is recorded. No cue is removed or edited."""
    issues = episode.issues

    for scene in episode.scenes:
        missing = [name for name, value in (("heading", scene.heading), ("start", scene.start), ("end", scene.end))
                   if value is None]
        if missing:
            scene.issues.append("incomplete_scene:" + ",".join(missing))
            issues.append(ParseIssue(episode.number, episode.file_name, scene.source_line, "incomplete_scene",
                                     f"Scene {scene.number} is missing {', '.join(missing)}"))
        if scene.start is not None and scene.end is not None and scene.end <= scene.start:
            scene.issues.append("scene_end_not_after_start")
            issues.append(ParseIssue(episode.number, episode.file_name, scene.source_line,
                                     "scene_end_not_after_start", f"Scene {scene.number}"))

    if not episode.scenes:
        issues.append(ParseIssue(episode.number, episode.file_name, None, "no_scenes", "No scene blocks found"))
    if not episode.cues:
        issues.append(ParseIssue(episode.number, episode.file_name, None, "no_cues", "No cues found"))

    scene_by_number = {scene.number: scene for scene in episode.scenes}
    seen_keys: dict[tuple, str] = {}
    last_on_track: dict[str, Cue] = {}

    for cue in episode.cues:
        for problem in cue.issues:
            issues.append(ParseIssue(episode.number, episode.file_name, cue.source_line,
                                     problem.split(":")[0], f"{cue.raw_label}: {problem}", cue.cue_id))

        # The same label, time and text appearing twice is a repeated cue.
        key = (cue.raw_label, cue.start, cue.end, cue.text)
        if key in seen_keys:
            cue.issues.append(f"repeated_cue_of:{seen_keys[key]}")
            issues.append(ParseIssue(episode.number, episode.file_name, cue.source_line, "repeated_cue",
                                     f"Same as {seen_keys[key]}", cue.cue_id))
        else:
            seen_keys[key] = cue.cue_id

        if not cue.has_valid_time:
            continue

        scene = scene_by_number.get(cue.scene) if cue.scene is not None else None
        if scene is not None:
            if scene.end is not None and cue.end > scene.end + OVERLAP_TOLERANCE:
                cue.issues.append("cue_after_scene_end")
                issues.append(ParseIssue(episode.number, episode.file_name, cue.source_line, "cue_after_scene_end",
                                         f"Cue ends {format_timestamp(cue.end)}, scene {scene.number} "
                                         f"ends {format_timestamp(scene.end)}", cue.cue_id))
            if scene.start is not None and cue.start < scene.start - OVERLAP_TOLERANCE:
                cue.issues.append("cue_before_scene_start")
                issues.append(ParseIssue(episode.number, episode.file_name, cue.source_line, "cue_before_scene_start",
                                         f"Cue starts {format_timestamp(cue.start)}, scene {scene.number} "
                                         f"starts {format_timestamp(scene.start)}", cue.cue_id))

        # Camera over dialogue is normal because they are separate tracks.
        # Only overlaps inside the same track are worth recording.
        previous = last_on_track.get(cue.kind)
        if previous is not None:
            if cue.start < previous.end - OVERLAP_TOLERANCE:
                cue.issues.append(f"overlaps_same_track:{previous.cue_id}")
                issues.append(ParseIssue(episode.number, episode.file_name, cue.source_line,
                                         f"overlap_{cue.kind}",
                                         f"Starts {format_timestamp(cue.start)}, before {previous.cue_id} ends "
                                         f"{format_timestamp(previous.end)}", cue.cue_id))
            if cue.start < previous.start - OVERLAP_TOLERANCE:
                cue.issues.append(f"out_of_time_order_after:{previous.cue_id}")
                issues.append(ParseIssue(episode.number, episode.file_name, cue.source_line,
                                         f"out_of_order_{cue.kind}",
                                         f"Starts {format_timestamp(cue.start)}, earlier than {previous.cue_id} "
                                         f"at {format_timestamp(previous.start)}", cue.cue_id))
        if previous is None or cue.end >= previous.end:
            last_on_track[cue.kind] = cue


# Far above a real pack (51 files, 0.5 MB, largest file 16 KB), low enough that a hostile ZIP cannot fill memory.
MAX_ZIP_MEMBERS = 500
MAX_MEMBER_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024


def check_zip_limits(archive: zipfile.ZipFile) -> None:
    """Refuse a ZIP with too many files or too much text once unpacked. Uses the sizes the ZIP declares, which
    are also the most Python will unpack for each member."""
    members = [info for info in archive.infolist() if not info.is_dir()]
    if len(members) > MAX_ZIP_MEMBERS:
        raise ScreenplayPackError(f"The ZIP holds {len(members)} files; at most {MAX_ZIP_MEMBERS} are accepted.")
    largest = max(members, key=lambda info: info.file_size, default=None)
    if largest is not None and largest.file_size > MAX_MEMBER_BYTES:
        raise ScreenplayPackError(f"{largest.filename} is {largest.file_size:,} bytes unpacked; "
                                  f"at most {MAX_MEMBER_BYTES:,} are accepted per file.")
    total = sum(info.file_size for info in members)
    if total > MAX_TOTAL_BYTES:
        raise ScreenplayPackError(f"The ZIP unpacks to {total:,} bytes; at most {MAX_TOTAL_BYTES:,} are accepted.")


def load_pack(path: str | Path) -> tuple[list[Episode], list[ParseIssue]]:
    """Load every episode from a ZIP file or a folder.

    Returns the episodes sorted by number, and problems with the pack itself.
    Raises ScreenplayPackError if nothing usable exists.
    """
    path = Path(path)
    if not path.exists():
        raise ScreenplayPackError(f"Input not found: {path}")

    named_texts: list[tuple[str, str]] = []
    pack_issues: list[ParseIssue] = []

    if path.is_dir():
        for file_path in sorted(path.rglob("*.txt")):
            # Forward slashes, as in a ZIP, so results name files the same way on every platform.
            named_texts.append((file_path.relative_to(path).as_posix(), _read_text(file_path.read_bytes(), str(file_path), pack_issues)))
    else:
        try:
            with zipfile.ZipFile(path) as archive:
                check_zip_limits(archive)  # Before anything is decompressed.
                bad_member = archive.testzip()
                if bad_member:
                    raise ScreenplayPackError(f"ZIP is corrupted at member: {bad_member}")
                for name in sorted(archive.namelist()):
                    if name.endswith("/"):
                        continue
                    base = PurePosixPath(name).name
                    # macOS adds hidden metadata files to ZIPs. They are not episodes.
                    if name.startswith("__MACOSX/") or base.startswith("."):
                        continue
                    if not base.lower().endswith(".txt"):
                        pack_issues.append(ParseIssue(None, name, None, "ignored_non_txt_file", "Not a .txt file"))
                        continue
                    named_texts.append((name, _read_text(archive.read(name), name, pack_issues)))
        except zipfile.BadZipFile as error:
            raise ScreenplayPackError(f"Not a valid ZIP file: {path.name} ({error})") from error

    if not named_texts:
        raise ScreenplayPackError(f"No screenplay .txt files found in {path.name}")

    episodes_by_number: dict[int, Episode] = {}
    for name, text in named_texts:
        episode = parse_episode_text(text, name)
        if episode.number == 0:
            pack_issues.append(ParseIssue(None, name, None, "unusable_episode",
                                          "No episode number anywhere, so this file was not processed"))
            continue
        existing = episodes_by_number.get(episode.number)
        if existing is not None:
            same = existing.content_hash == episode.content_hash
            pack_issues.append(ParseIssue(
                episode.number, name, None, "duplicate_episode",
                f"Episode {episode.number} also in {existing.file_name}"
                f" ({'identical content' if same else 'DIFFERENT content'}). First file kept.",
            ))
            continue
        episodes_by_number[episode.number] = episode

    if not episodes_by_number:
        raise ScreenplayPackError("Files were found but none could be used as an episode")

    numbers = sorted(episodes_by_number)
    missing = sorted(set(range(numbers[0], numbers[-1] + 1)) - set(numbers))
    if missing:
        pack_issues.append(ParseIssue(None, path.name, None, "missing_episodes",
                                      f"No file for episode(s): {missing}"))
    return [episodes_by_number[number] for number in numbers], pack_issues


def _read_text(data: bytes, name: str, pack_issues: list[ParseIssue]) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pack_issues.append(ParseIssue(None, name, None, "not_utf8", "Decoded as Latin-1 instead of UTF-8"))
        return data.decode("latin-1")


def issue_to_dict(issue: ParseIssue) -> dict:
    return asdict(issue)
