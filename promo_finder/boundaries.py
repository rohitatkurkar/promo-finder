"""Turn a hook cue and an ending cue into a real clip, or reject the pair.

This is the rule that protects the whole tool: every clip time comes from a cue
in the screenplay. A language model can only point at cue IDs. It never supplies
a time, and this file never invents one.

Nothing is forced to fit. If a pair cannot make a valid clip, the reason is
returned so it can be reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .parser import ACTION, CAMERA, DIALOGUE, STORY_KINDS, Cue, Episode, format_timestamp

MIN_DURATION = 20.0
MAX_DURATION = 60.0
HOOK_WINDOW = 3.0

# Scripts overlap neighbouring lines by small amounts. A line only counts as
# "in progress" at a boundary when it runs past the boundary by more than this.
LINE_TOLERANCE = 0.25

# A real editor cuts on a shot change. We move a boundary to the nearest shot
# change only if it is this close, so the moment itself stays the same.
MAX_START_SNAP = 1.0
MAX_END_SNAP = 1.5

# One word replies and bare names tell a new viewer nothing.
BACKCHANNEL_WORDS = {
    "yes", "no", "what", "oh", "ah", "ahh", "ahhh", "hmm", "good", "okay", "ok", "right",
    "well", "why", "who", "how", "where", "when", "please", "thanks", "enough", "stop", "wait",
}


@dataclass
class Clip:
    episode: int
    start: float
    end: float
    start_cue_id: str
    end_cue_id: str
    hook_cue_id: str
    ending_cue_id: str
    hook_offset: float
    adjustments: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)

    @property
    def key(self) -> str:
        """Stable ID for a clip. The same cue pair gets the same key in every run."""
        return f"{self.hook_cue_id}__{self.ending_cue_id.split('_')[1]}"


@dataclass
class ClipResult:
    clip: Clip | None
    reason: str | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.clip is not None


def _reject(reason: str, detail: str = "") -> ClipResult:
    return ClipResult(None, reason, detail)


def word_list(text: str) -> list[str]:
    return re.findall(r"[a-z']+", re.sub(r"\[[^\]]*\]", " ", text.lower()))


def is_continuation(cue: Cue) -> bool:
    """True when a line picks up a sentence begun in an earlier cue, like '...let her go.'"""
    return cue.kind == DIALOGUE and cue.text.lstrip().startswith(("...", "…", "—", "--"))


def line_is_cut_off(cue: Cue) -> bool:
    return cue.kind == DIALOGUE and cue.text.rstrip().endswith(("...", "…", "—", "--"))


def next_dialogue(episode: Episode, cue: Cue) -> Cue | None:
    seen = False
    for other in episode.cues:
        if other.cue_id == cue.cue_id:
            seen = True
            continue
        if seen and other.kind == DIALOGUE:
            return other
    return None


def previous_dialogue(episode: Episode, cue: Cue) -> Cue | None:
    last = None
    for other in episode.cues:
        if other.cue_id == cue.cue_id:
            return last
        if other.kind == DIALOGUE:
            last = other
    return last


def sentence_continues_after(episode: Episode, cue: Cue) -> bool:
    """True when the same speaker finishes this sentence in the next line."""
    following = next_dialogue(episode, cue)
    return bool(
        following is not None
        and line_is_cut_off(cue)
        and is_continuation(following)
        and following.speaker == cue.speaker
    )


def is_meaningful(cue: Cue, known_names: set[str] | None = None) -> bool:
    """A cue a new viewer could react to, not a bare 'Yes.' or a name called out."""
    if cue.kind not in STORY_KINDS or not cue.has_valid_time or not cue.text.strip():
        return False
    words = word_list(cue.text)
    if cue.kind == ACTION:
        return len(words) >= 3
    if not words:
        return False
    if len(words) == 1:
        if words[0] in BACKCHANNEL_WORDS:
            return False
        if known_names and words[0] in known_names:
            return False
    return True


def known_names_for(episode: Episode) -> set[str]:
    """Lower case single word names taken from this episode's speaker labels."""
    names = set()
    for cue in episode.cues:
        if cue.kind == DIALOGUE and cue.speaker:
            for word in word_list(cue.speaker):
                if word not in ("the", "lady", "lord", "sir", "miss", "mrs", "mr", "father"):
                    names.add(word)
    return names


def dialogue_in_progress(episode: Episode, moment: float) -> Cue | None:
    """Return a dialogue line being spoken across this moment, if there is one."""
    for cue in episode.cues:
        if (
            cue.kind == DIALOGUE
            and cue.has_valid_time
            and cue.start < moment - LINE_TOLERANCE
            and cue.end > moment + LINE_TOLERANCE
        ):
            return cue
    return None


def action_in_progress(episode: Episode, moment: float) -> Cue | None:
    """Return an action already happening at this moment, if there is one."""
    for cue in episode.cues:
        if (
            cue.kind == ACTION
            and cue.has_valid_time
            and cue.start < moment - LINE_TOLERANCE
            and cue.end > moment + LINE_TOLERANCE
        ):
            return cue
    return None


def _dialogue_starts_between(episode: Episode, low: float, high: float) -> bool:
    return any(
        cue.kind == DIALOGUE and cue.has_valid_time and low + LINE_TOLERANCE <= cue.start < high
        for cue in episode.cues
    )


def _shot_change_before(episode: Episode, moment: float) -> Cue | None:
    """Latest camera cue starting at or shortly before this moment."""
    best = None
    for cue in episode.cues:
        if cue.kind == CAMERA and cue.has_valid_time and moment - MAX_START_SNAP <= cue.start <= moment:
            if best is None or cue.start > best.start:
                best = cue
    return best


def _shot_change_after(episode: Episode, moment: float) -> Cue | None:
    """Earliest camera cue ending at or shortly after this moment."""
    best = None
    for cue in episode.cues:
        if cue.kind == CAMERA and cue.has_valid_time and moment <= cue.end <= moment + MAX_END_SNAP:
            if best is None or cue.end < best.end:
                best = cue
    return best


def cues_in_range(episode: Episode, start: float, end: float) -> list[Cue]:
    """Cues that play inside the range. A cue only touching an edge is left out."""
    selected = [
        cue for cue in episode.cues
        if cue.has_valid_time and cue.end > start + LINE_TOLERANCE and cue.start < end - LINE_TOLERANCE
    ]
    return sorted(selected, key=lambda cue: cue.start)


def first_story_cue(episode: Episode, start: float, end: float, names: set[str] | None = None) -> Cue | None:
    """First meaningful dialogue or action cue starting at or after the clip start."""
    for cue in sorted((c for c in episode.cues if c.has_valid_time), key=lambda c: c.start):
        if cue.start < start - LINE_TOLERANCE or cue.start >= end:
            continue
        if is_meaningful(cue, names):
            return cue
    return None


def build_clip(episode: Episode, hook: Cue, ending: Cue) -> ClipResult:
    """Make the clip for this hook and ending. See the module note for the rules."""
    if hook.kind not in STORY_KINDS:
        return _reject("hook_not_a_story_event", f"{hook.cue_id} is a {hook.kind} cue, which cannot be a hook by itself")
    if ending.kind not in STORY_KINDS:
        return _reject("ending_not_a_story_event", f"{ending.cue_id} is a {ending.kind} cue, which cannot be an ending by itself")
    if not hook.has_valid_time:
        return _reject("hook_has_no_valid_time", hook.cue_id)
    if not ending.has_valid_time:
        return _reject("ending_has_no_valid_time", ending.cue_id)
    if ending.end <= hook.start:
        return _reject("ending_before_hook", f"{ending.cue_id} ends before {hook.cue_id} starts")
    if is_continuation(hook):
        return _reject("hook_starts_mid_sentence", f"{hook.cue_id} continues a sentence from an earlier line")

    names = known_names_for(episode)
    if not is_meaningful(hook, names):
        return _reject("hook_not_meaningful", f"{hook.cue_id} is too slight to open a promo")

    raw_length = ending.end - hook.start
    if raw_length > MAX_DURATION + MAX_START_SNAP:
        return _reject("too_long", f"Hook to ending is {raw_length:.1f}s, over the {MAX_DURATION:.0f}s limit")
    if raw_length < MIN_DURATION - MAX_START_SNAP - MAX_END_SNAP:
        return _reject("too_short", f"Hook to ending is {raw_length:.1f}s, under the {MIN_DURATION:.0f}s limit")

    start, start_cue_id = hook.start, hook.cue_id
    end, end_cue_id = ending.end, ending.cue_id
    adjustments: list[str] = []
    warnings: list[str] = []

    # Never begin inside someone else's line.
    in_progress = dialogue_in_progress(episode, start)
    if in_progress is not None:
        moved = hook.start - in_progress.start
        if moved <= HOOK_WINDOW and not is_continuation(in_progress):
            adjustments.append(
                f"Start moved {moved:.2f}s earlier to {in_progress.cue_id}, because that line was still being spoken."
            )
            start, start_cue_id = in_progress.start, in_progress.cue_id
        else:
            return _reject("starts_inside_dialogue", f"{in_progress.cue_id} is mid line at the hook")

    # Do not open partway through a physical action, or the viewer sees the effect without the cause.
    # Keep stepping back, because a flinch can overlap the blow that caused it.
    already_happening = action_in_progress(episode, start)
    while (
        already_happening is not None
        and hook.start - already_happening.start <= HOOK_WINDOW
        and dialogue_in_progress(episode, already_happening.start) is None
    ):
        adjustments.append(
            f"Start moved {start - already_happening.start:.2f}s earlier to {already_happening.cue_id}, "
            "because that action was already happening."
        )
        start, start_cue_id = already_happening.start, already_happening.cue_id
        already_happening = action_in_progress(episode, start)

    # Never end inside someone else's line.
    in_progress = dialogue_in_progress(episode, end)
    if in_progress is not None:
        if in_progress.end - start <= MAX_DURATION:
            adjustments.append(
                f"End moved {in_progress.end - end:.2f}s later to {in_progress.cue_id}, so that line is not cut."
            )
            end, end_cue_id = in_progress.end, in_progress.cue_id
        else:
            return _reject("cuts_through_dialogue", f"Ending would cut {in_progress.cue_id}, and finishing it passes 60s")

    # Prefer clean cuts on shot changes, as long as the moment stays the same.
    snapped_start = snapped_end = None
    shot = _shot_change_before(episode, start)
    if (
        shot is not None
        and shot.start < start
        and dialogue_in_progress(episode, shot.start) is None
        and not _dialogue_starts_between(episode, shot.start, start)
    ):
        snapped_start = (start, start_cue_id)
        adjustments.append(f"Start moved {start - shot.start:.2f}s earlier to the shot change at {shot.cue_id}.")
        start, start_cue_id = shot.start, shot.cue_id

    shot = _shot_change_after(episode, end)
    if shot is not None and shot.end > end and not _dialogue_starts_between(episode, end, shot.end):
        snapped_end = (end, end_cue_id)
        adjustments.append(f"End moved {shot.end - end:.2f}s later to the shot change at {shot.cue_id}.")
        end, end_cue_id = shot.end, shot.cue_id

    # A shot change must never push an otherwise valid clip over the limit.
    if end - start > MAX_DURATION and snapped_end is not None:
        end, end_cue_id = snapped_end
        snapped_end = None
        adjustments.append("End shot change undone, to stay within 60s.")
    if end - start > MAX_DURATION and snapped_start is not None:
        start, start_cue_id = snapped_start
        snapped_start = None
        adjustments.append("Start shot change undone, to stay within 60s.")

    duration = end - start
    if duration > MAX_DURATION + 1e-6:
        return _reject("too_long", f"Clip is {duration:.2f}s, over the {MAX_DURATION:.0f}s limit")
    if duration < MIN_DURATION - 1e-6:
        return _reject("too_short", f"Clip is {duration:.2f}s, under the {MIN_DURATION:.0f}s limit")

    opener = first_story_cue(episode, start, end, names)
    if opener is None:
        return _reject("no_story_cue_in_clip", "Only camera or sound cues found")
    hook_offset = round(max(0.0, hook.start - start), 3)
    if opener.start - start > HOOK_WINDOW + 1e-6 or hook_offset > HOOK_WINDOW + 1e-6:
        return _reject(
            "hook_outside_three_seconds",
            f"First story cue {opener.cue_id} starts {opener.start - start:.2f}s in, hook starts {hook_offset:.2f}s in",
        )

    # These do not disqualify a clip, but a reviewer should know about them.
    if sentence_continues_after(episode, ending):
        warnings.append(f"Ends mid sentence: the speaker finishes this line in the next cue after {ending.cue_id}.")
    if line_is_cut_off(hook):
        warnings.append(f"Opening line {hook.cue_id} trails off, so check it reads as a complete thought.")
    inside = cues_in_range(episode, start, end)
    flagged = [cue.cue_id for cue in inside if cue.issues]
    if flagged:
        warnings.append("Contains cues with data notes: " + ", ".join(flagged[:5]))
    scene_numbers = sorted({cue.scene for cue in inside if cue.scene is not None})
    if len(scene_numbers) > 1:
        warnings.append(f"Crosses {len(scene_numbers)} scenes: {scene_numbers}.")

    return ClipResult(
        Clip(
            episode=episode.number,
            start=round(start, 3),
            end=round(end, 3),
            start_cue_id=start_cue_id,
            end_cue_id=end_cue_id,
            hook_cue_id=hook.cue_id,
            ending_cue_id=ending.cue_id,
            hook_offset=hook_offset,
            adjustments=adjustments,
            warnings=warnings,
        )
    )


def clip_summary(clip: Clip) -> str:
    return (
        f"E{clip.episode:02d} {format_timestamp(clip.start)} to {format_timestamp(clip.end)} "
        f"({clip.duration:.1f}s) {clip.hook_cue_id} to {clip.ending_cue_id}"
    )


def intersection_over_union(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Shared time divided by total time covered by both ranges."""
    shared = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    covered = (a_end - a_start) + (b_end - b_start) - shared
    return shared / covered if covered > 0 else 0.0
