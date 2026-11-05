"""Build the version of a clip that a viewer who knows nothing would experience.

The screenplay knows things a viewer cannot. A label like THE EX HUSBAND tells
the reader a relationship the viewer only sees as "a man in a coat". If the
cold viewer test read those labels, it would pass clips real viewers could not
follow. So speakers become SPEAKER A, SPEAKER B, and so on.

Spoken dialogue is never changed, because the viewer hears it. Acting notes are
dropped. Words that describe the production rather than the story, like
"cliffhanger", are removed so they cannot sway the judge.

Known limit: action and camera text can still hold narrative words such as "her
father", which a viewer may not yet know. Those are not rewritten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .boundaries import cues_in_range, word_list
from .parser import ACTION, CAMERA, DIALOGUE, SOUND, Cue, Episode

HONORIFICS = {"lady", "lord", "sir", "miss", "mrs", "mr", "dame"}
PRODUCTION_WORDS = re.compile(r"\b(cliffhanger|final beat)\b", re.IGNORECASE)
KIND_LABEL = {ACTION: "ACTION", CAMERA: "SHOT", SOUND: "SOUND"}
SPEAKER_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass
class BlindClip:
    rows: list[str]
    speaker_tokens: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(self.rows)


def speaker_root(label: str, labels_in_pack: set[str]) -> str:
    """Treat 'LADY ANNA' as 'ANNA' only if a bare 'ANNA' label also exists.

    That is the only merging allowed. LORD GREY and LADY GREY stay separate because
    no bare GREY label exists, and a surname alone does not make them one person.
    Merging is also only ever used inside one clip, so it cannot join two different
    people who shared a label in different episodes.
    """
    label = label.strip().upper()
    words = label.split()
    if len(words) >= 2 and words[0].lower() in HONORIFICS:
        bare = " ".join(words[1:])
        if bare in labels_in_pack:
            return bare
    return label


def collect_labels(episodes: list[Episode]) -> set[str]:
    return {cue.speaker.upper() for episode in episodes for cue in episode.cues
            if cue.kind == DIALOGUE and cue.speaker}


def _name_variants(label: str) -> list[str]:
    """Forms of a label that may appear in action or camera text."""
    cleaned = label.strip()
    words = cleaned.split()
    variants = {cleaned}
    if words and words[0].lower() in ("the", "a", "an"):
        variants.add(" ".join(words[1:]))
    if len(words) >= 2 and words[0].lower() in HONORIFICS:
        variants.add(" ".join(words[1:]))
    return sorted((variant for variant in variants if len(variant) >= 3), key=len, reverse=True)


def _replace_names(text: str, replacements: list[tuple[str, str]]) -> str:
    for name, token in replacements:
        text = re.sub(rf"\b(?:the\s+)?{re.escape(name)}\b", token, text, flags=re.IGNORECASE)
    return text


def blind_rows_for(cues: list[Cue], labels_in_pack: set[str], all_name_words: set[str]) -> BlindClip:
    tokens: dict[str, str] = {}
    label_token: dict[str, str] = {}
    for cue in cues:
        if cue.kind == DIALOGUE and cue.speaker:
            root = speaker_root(cue.speaker, labels_in_pack)
            if root not in tokens:
                tokens[root] = f"SPEAKER {SPEAKER_LETTERS[len(tokens) % 26]}"
            label_token[cue.speaker.upper()] = tokens[root]

    # Longest names first, so "Lady Anna" is replaced before "Anna".
    replacements: list[tuple[str, str]] = []
    for label, token in label_token.items():
        for variant in _name_variants(label):
            replacements.append((variant, token))
    for root, token in tokens.items():
        for variant in _name_variants(root):
            replacements.append((variant, token))
    replacements = sorted(set(replacements), key=lambda pair: len(pair[0]), reverse=True)

    rows: list[str] = []
    for cue in cues:
        if cue.kind == DIALOGUE:
            token = label_token.get((cue.speaker or "").upper(), "SPEAKER ?")
            mode = " (voice heard, speaker not visible)" if cue.voice_mode in ("voice_over", "off_screen") else ""
            rows.append(f'{token}{mode}: "{cue.text}"')
        else:
            text = _replace_names(cue.text, replacements)
            # Other characters' names mean nothing to this viewer, so they become "someone".
            for word in all_name_words:
                if word and re.search(rf"\b{re.escape(word)}\b", text, flags=re.IGNORECASE):
                    text = re.sub(rf"\b{re.escape(word)}\b", "someone", text, flags=re.IGNORECASE)
            text = PRODUCTION_WORDS.sub("moment", text)
            rows.append(f"[{KIND_LABEL.get(cue.kind, 'NOTE')}] {text}")
    return BlindClip(rows, {label: token for label, token in label_token.items()})


def pack_name_words(episodes: list[Episode]) -> set[str]:
    """Single word character names, taken from labels that look like real names."""
    labels = collect_labels(episodes)
    descriptive = {"the", "a", "an", "of", "in", "with", "man", "woman", "lady", "lord", "guard", "maid", "noble",
                   "nobleman", "noblewoman", "matriarch", "priest", "father", "mother", "son", "groom", "stranger",
                   "bearded", "mysterious", "scarred", "blond", "elder", "old", "high", "royal", "crown", "official",
                   "judge", "constable", "police", "thug", "bald", "tall", "third", "cap", "gold", "gown", "peasant",
                   "housekeeper", "butler", "footman", "villager", "informant", "conspirator", "sentry", "loyalist",
                   "scout", "fighter", "cart", "driver", "townsman", "aristocratic", "former", "voice", "off", "screen",
                   "dowager", "duchess"}
    names = set()
    for label in labels:
        for word in word_list(label):
            if word not in descriptive and len(word) >= 3 and word not in HONORIFICS and not word.endswith("'s"):
                names.add(word)
    return names


def blind_clip(episode: Episode, start: float, end: float, labels_in_pack: set[str], name_words: set[str]) -> BlindClip:
    """The whole clip as a cold viewer would experience it."""
    return blind_rows_for(cues_in_range(episode, start, end), labels_in_pack, name_words)


def blind_first_three_seconds(episode: Episode, start: float, labels_in_pack: set[str], name_words: set[str]) -> BlindClip:
    """Only what begins in the first three seconds, for the scroll stopping test."""
    cues = sorted(
        (cue for cue in episode.cues if cue.has_valid_time and start - 0.25 <= cue.start <= start + 3.0),
        key=lambda cue: cue.start,
    )
    return blind_rows_for(cues, labels_in_pack, name_words)


def normalise_for_match(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", text.lower().replace("’", "'")).split())


def quote_is_in(quote: str, text: str) -> bool:
    """True when a quote really appears in the text, ignoring case and punctuation."""
    quote_clean = normalise_for_match(quote)
    return bool(quote_clean) and quote_clean in normalise_for_match(text)
