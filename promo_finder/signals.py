"""Simple measurable signals used by Basic mode. No language model is involved.

These are clues, not understanding. Keyword lists are only one input, and each
one is capped. The structural clues matter as much: where a line falls in the
episode, how fast people are trading lines, what the script's own acting notes
say, and whether the next line answers the last one.

Words like "cliffhanger" in camera or sound cues are deliberately ignored. Only
dialogue and action cues feed these signals.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .boundaries import (
    Clip,
    cues_in_range,
    first_story_cue,
    is_meaningful,
    known_names_for,
    line_is_cut_off,
    next_dialogue,
    previous_dialogue,
    sentence_continues_after,
    word_list,
)
from .parser import ACTION, DIALOGUE, Cue, Episode

# The script's own acting notes are a human written record of emotional intensity.
HIGH_INTENSITY = {
    "screaming", "shouting", "furious", "enraged", "hysterical", "desperate", "terrified", "panicked",
    "frantic", "sobbing", "weeping", "outraged", "accusing", "accusatory", "venomous", "threatening",
    "menacing", "chilling", "sinister", "vicious", "ruthless", "deadly", "horrified", "shocked",
    "begging", "gasping", "agonized", "thunderous", "booming", "vindictive", "malicious", "condemning",
    "dangerous", "shattered", "heartbroken", "despairing", "crying out", "cruel",
}
MEDIUM_INTENSITY = {
    "cold", "defiant", "mocking", "scornful", "taunting", "spiteful", "gloating", "smug", "harsh",
    "fierce", "demanding", "urgent", "commanding", "stern", "bitter", "sneering", "derisive",
    "contemptuous", "trembling", "tearful", "pleading", "shaken", "stunned", "alarmed", "anxious",
    "scheming", "calculating", "imperious", "cutting", "indignant", "scathing", "resolute", "steely",
    "unyielding", "dark", "ominous", "grim", "breathless", "broken", "pained", "intense", "fearful",
}
LOW_INTENSITY = {
    "gentle", "soft", "warm", "tender", "quiet", "reassuring", "calm", "sincere", "loving", "playful",
    "amused", "relieved", "grateful", "humble", "peaceful", "content", "comforted", "softly", "reflective",
    "curious", "faint", "modest", "earnest",
}

# Physical events a scrolling viewer would notice. Verbs in action cues only.
# These are things being DONE. Someone flinching afterwards is listed separately below.
PHYSICAL_EVENTS = re.compile(
    r"\b(strikes?|slams?|drags?|grabs?|shoves?|hurls?|smash(?:es)?|explodes?|explosion|fireball|"
    r"bursts?|lunges?|tackles?|yanks?|snatch(?:es)?|rips?|whips?|flings?|thrusts?|shatters?|"
    r"seiz\w+|plunges?|crash(?:es)?|attacks?|swings?|storms?|inferno|flames?|blood\w*|gash\w*|chained|shackled)\b",
    re.IGNORECASE,
)

# Reactions are not events in themselves. They show that the moment before them landed.
# Camera and action text may support a moment this way, but can never be the moment.
REACTIONS = re.compile(
    r"\b(gasps?|gasping|widen\w*|freez\w*|frozen|stunned|shock\w*|horror|horrified|pal(?:e|es|ed)|tears?|"
    r"trembl\w*|recoil\w*|agape|disbelief|terror|dread|panic\w*|stagger\w*|collaps\w*|convuls\w*)\b",
    re.IGNORECASE,
)

STAKES = re.compile(
    r"\b(hang\w*|gallows|noose|execut\w+|die|dies|dying|dead|death|kill\w*|murder\w*|poison\w*|arsenic|"
    r"witch\w*|condemn\w*|arrest\w*|prison\w*|dungeon|betray\w*|stole|steal\w*|stolen|planted|trait\w+|"
    r"treason|disowned?|burn\w*|lie|liar|lying|secret|alive|revenge|destroy\w*|ruin\w*)\b",
    re.IGNORECASE,
)

RELATIONSHIPS = re.compile(
    r"\b(husband|wife|sister|brother|father|mother|son|daughter|married|marry|marrying|wedding|bride|groom|"
    r"fianc\w+|family|aunt|uncle|cousin|duke|duchess|lady|lord|maid|servant|soldier|widow|heir)\b",
    re.IGNORECASE,
)

THREAT_OR_REVEAL = re.compile(
    r"\b(you will|you'll|i will|i'll|will hang|will die|or your|or else|if you|you knew|it was you|"
    r"you (?:stole|lied|planted|abandoned|betrayed|poisoned|killed)|someone is|he is|she is|is my|"
    r"never going to|i know what|the truth|you are (?:not|under|accused)|they (?:are|will|took))\b",
    re.IGNORECASE,
)

# Lines that close a story beat. Ending on these lowers curiosity.
RESOLVING = re.compile(
    r"\b(thank you|you saved|it's over|it is over|you are safe|you're safe|i've got you|i found it|"
    r"we are leaving|take me home|let's go|i forgive|at last|it is done|it is enough|we did it)\b",
    re.IGNORECASE,
)

CONTEXT_DEPENDENT_OPENING = re.compile(
    r"^\s*(and|but|so|then|because|it|that|this|those|these|they|he|she|him|her|there|them)\b", re.IGNORECASE
)
THIRD_PERSON = re.compile(r"\b(she|he|they|her|him|them)\b", re.IGNORECASE)
# An unexpected arrival is one of the classic promo endings.
ARRIVAL = re.compile(
    r"\b(bursts? (?:open|in|into|through)|swings? open|slams? open|storms? (?:in|into|forward)|"
    r"emerg\w+ (?:from|through)|steps? (?:in|inside|through)|marches? (?:in|into|toward)|appears?|arrives?)\b",
    re.IGNORECASE,
)
POINTING_WORD = re.compile(r"\b(that|this|it|there|those|these|them|him|her)\b", re.IGNORECASE)
# The writers' own notes for the next episode, saying this episode stopped on an open moment.
NEXT_EPISODE_SAYS_OPEN = re.compile(r"\b(cliffhanger|climax|revelation)\b", re.IGNORECASE)
STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "at", "for", "with", "from", "by", "as", "is", "are",
    "was", "were", "be", "been", "her", "his", "their", "she", "he", "they", "it", "its", "that", "this", "who", "whom",
    "which", "when", "while", "after", "before", "into", "only", "then", "than", "not", "no", "has", "have", "had",
    "new", "own", "all", "them", "him", "out", "up", "over", "under", "just", "so", "very", "will",
}
PAST_REFERENCE = re.compile(
    r"\b(yesterday|last night|last time|again|remember|as i said|the other day|the first time|before that|earlier|that day)\b",
    re.IGNORECASE,
)

ADULT_CONTENT = re.compile(r"\b(naked|nude|shirtless|bare skin|bare chest|passionate embrace|intimate|bedroom scene|sex\w*|forbidden entanglement)\b", re.IGNORECASE)
GRAPHIC_CONTENT = re.compile(r"\b(blood\w*|gash\w*|lacerat\w*|branding|searing|torture\w*|wound\w*|corpse|noose|shredded)\b", re.IGNORECASE)


@dataclass
class SignalScore:
    value: float
    reasons: list[str] = field(default_factory=list)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def delivery_level(cue: Cue) -> float:
    """Read a line's intensity from the script's acting note. 0.5 means no information."""
    if not cue.delivery:
        return 0.5
    parts = [part.strip().lower() for part in re.split(r"[,/&]| and ", cue.delivery) if part.strip()]
    high = sum(1 for part in parts if part in HIGH_INTENSITY)
    medium = sum(1 for part in parts if part in MEDIUM_INTENSITY)
    low = sum(1 for part in parts if part in LOW_INTENSITY)
    if high:
        return 1.0
    if medium and not low:
        return 0.75
    if low and not medium:
        return 0.15
    if medium and low:
        return 0.5
    return 0.5


def is_physical_event(cue: Cue) -> bool:
    return cue.kind == ACTION and bool(PHYSICAL_EVENTS.search(cue.text))


def hook_signal(episode: Episode, hook: Cue, window_start: float | None = None) -> SignalScore:
    """How likely this opening stops a scroll, using only the first three seconds."""
    start = hook.start if window_start is None else window_start
    early = [
        cue for cue in episode.cues
        if cue.has_valid_time and cue.kind in (DIALOGUE, ACTION) and start - 0.05 <= cue.start <= start + 3.0
    ]
    value = 0.0
    reasons: list[str] = []

    if any(is_physical_event(cue) for cue in early):
        value += 0.35
        reasons.append("physical event in the first 3 seconds")

    lines = [cue for cue in early if cue.kind == DIALOGUE]
    if lines:
        level = max(delivery_level(cue) for cue in lines)
        value += 0.25 * level
        if level >= 0.75:
            reasons.append("script marks the delivery as intense")
        text = " ".join(cue.text for cue in lines)
        if THREAT_OR_REVEAL.search(text):
            value += 0.2
            reasons.append("threat, accusation or reveal wording")
        if STAKES.search(text):
            value += 0.15
            reasons.append("high stakes wording")
        if "!" in text:
            value += 0.08
        words = word_list(hook.text)
        if hook.kind == DIALOGUE and 3 <= len(words) <= 14:
            value += 0.07  # Short lines land faster than speeches.
        if hook.kind == DIALOGUE and len(words) > 22:
            value -= 0.1
            reasons.append("opening line is long")
        if hook.kind == DIALOGUE and (CONTEXT_DEPENDENT_OPENING.match(hook.text) or THIRD_PERSON.search(hook.text)):
            value -= 0.15
            reasons.append("opening line leans on earlier context")
    if hook.kind == DIALOGUE and delivery_level(hook) < 0.3:
        value -= 0.1
        reasons.append("soft delivery")
    if hook.kind == DIALOGUE:
        words = word_list(hook.text)
        if len(words) <= 6 and POINTING_WORD.search(hook.text):
            value -= 0.12
            reasons.append("short line pointing at something the viewer has not seen")
        before = previous_dialogue(episode, hook)
        if before is not None and before.speaker != hook.speaker and before.has_valid_time and hook.start - before.end < 1.5:
            # A promo should start where an exchange starts, not on someone's reply to it.
            if before.text.rstrip().endswith("?"):
                value -= 0.12
                reasons.append("answers a question the viewer did not hear")
            if len(words) <= 8:
                value -= 0.2
                reasons.append("a short reply to a line the viewer did not hear")
        if silence_before(episode, hook) >= 2.0:
            value += 0.1
            reasons.append("a new exchange begins after a pause")
    elif hook.kind == ACTION and REACTIONS.search(hook.text) and not is_physical_event(hook):
        # Someone flinching, without the viewer having seen what caused it.
        value -= 0.25
        reasons.append("opens on a reaction, after the event that caused it")
    landed = reaction_after(episode, hook)
    if landed:
        value += 0.15 * landed
        reasons.append("the script shows this moment landing on someone")
    return SignalScore(clamp(value), reasons)


def silence_before(episode: Episode, cue: Cue) -> float:
    """Seconds since the last spoken line ended. A pause before a line marks a new exchange."""
    if not cue.has_valid_time:
        return 0.0
    earlier = [c.end for c in episode.cues if c.kind == DIALOGUE and c.has_valid_time and c.start < cue.start]
    return cue.start - max(earlier) if earlier else cue.start


def silence_after(episode: Episode, cue: Cue) -> float:
    """Seconds until the next spoken line. Writers hold on moments that matter."""
    if not cue.has_valid_time:
        return 0.0
    later = [c.start for c in episode.cues if c.kind == DIALOGUE and c.has_valid_time and c.start > cue.start]
    return min(later) - cue.end if later else 0.0


def reaction_after(episode: Episode, cue: Cue, window: float = 3.5) -> float:
    """Did this moment land? 1.0 for an intense reply from someone else, 0.7 for a described reaction, else 0."""
    if not cue.has_valid_time:
        return 0.0
    best = 0.0
    for other in episode.cues:
        if not other.has_valid_time or other.cue_id == cue.cue_id:
            continue
        if not cue.start < other.start <= cue.end + window:
            continue
        if other.kind == DIALOGUE:
            if other.speaker != cue.speaker and delivery_level(other) >= 0.75:
                best = max(best, 1.0)
        elif other.kind != "sound" and REACTIONS.search(other.text):
            best = max(best, 0.7)
    return best


def speaker_continues(episode: Episode, cue: Cue) -> bool:
    """True when the same person keeps talking straight after this line, so the thought is not finished."""
    following = next_dialogue(episode, cue)
    return bool(
        cue.kind == DIALOGUE and following is not None and following.speaker == cue.speaker
        and following.has_valid_time and cue.has_valid_time and following.start - cue.end < 1.0
    )


def stem(word: str) -> str:
    """A rough word root, so 'poisoned' and 'poisoning' count as the same word."""
    word = word.lower().removesuffix("'s")
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    for ending in ("ing", "ed", "es", "s"):
        if len(word) > len(ending) + 3 and word.endswith(ending):
            return word[: -len(ending)]
    return word


def content_stems(text: str, skip: set[str] | None = None) -> set[str]:
    skip = skip or set()
    return {stem(word) for word in word_list(text) if word not in STOP_WORDS and word not in skip and len(word) > 2}


def key_moment_signal(episode: Episode, clip: Clip) -> SignalScore:
    """How much of the writer's own episode summary this clip actually covers.

    This is the nearest thing Basic mode has to knowing what matters in an episode.
    It helps to find moments only. The understanding signal never reads the summary.
    """
    summary = content_stems(episode.logline, known_names_for(episode))
    if not summary:
        return SignalScore(0.5, ["no episode summary to compare with"])
    inside = cues_in_range(episode, clip.start, clip.end)
    shown = content_stems(" ".join(cue.text for cue in inside if cue.kind in (DIALOGUE, ACTION)))
    covered = summary & shown
    # A longer clip covers more words just by being longer, so this is scaled to a 40 second clip.
    share = len(covered) / len(summary) * min(1.0, 40.0 / max(clip.duration, 1.0))
    reasons = ["covers the episode's main event"] if share >= 0.25 else []
    return SignalScore(clamp(share / 0.4), reasons)


def _is_episode_final_beat(episode: Episode, cue: Cue) -> bool:
    """The last line spoken, or the last thing that happens."""
    story = [c for c in episode.cues if c.kind in (DIALOGUE, ACTION) and c.has_valid_time]
    lines = [c for c in story if c.kind == DIALOGUE]
    final_ids = {story[-1].cue_id} if story else set()
    if lines:
        final_ids.add(lines[-1].cue_id)
    return cue.cue_id in final_ids


def _is_scene_final_beat(episode: Episode, cue: Cue) -> bool:
    story = [c for c in episode.cues if c.kind in (DIALOGUE, ACTION) and c.has_valid_time and c.scene == cue.scene]
    return bool(story) and story[-1].cue_id == cue.cue_id


def ending_signal(episode: Episode, ending: Cue, next_notes: str = "") -> SignalScore:
    """How likely it is that stopping here leaves a question open.

    next_notes is the continuity note of the following episode. It is plot information
    written by the show's writers, unlike a sound cue describing music, and it can only
    confirm an episode's final beat. It never adds anything to a line mid episode.
    """
    value = 0.0
    reasons: list[str] = []
    level = delivery_level(ending) if ending.kind == DIALOGUE else 0.5

    if _is_episode_final_beat(episode, ending):
        value += 0.35
        reasons.append("the episode's own final beat")
        if NEXT_EPISODE_SAYS_OPEN.search(next_notes or ""):
            value += 0.2
            reasons.append("the next episode's notes confirm it stopped on an open moment")
    elif _is_scene_final_beat(episode, ending):
        value += 0.1
        reasons.append("final beat of a scene")

    if ending.kind == DIALOGUE:
        text = ending.text
        value += 0.2 * level
        if level >= 0.75:
            reasons.append("script marks the final line as intense")
        if THREAT_OR_REVEAL.search(text):
            value += 0.2
            reasons.append("final line threatens or reveals")
        if STAKES.search(text):
            value += 0.12
            reasons.append("final line carries high stakes")
        if text.rstrip().endswith("?"):
            following = next_dialogue(episode, ending)
            answered_soon = following is not None and following.speaker != ending.speaker
            if level >= 0.75:
                value += 0.15
                reasons.append("tense question left hanging")
                if answered_soon:
                    value += 0.05
            else:
                # A calm question is not suspense just because it has a question mark.
                value -= 0.05
                reasons.append("question, but nothing marks it as tense")
        if line_is_cut_off(ending):
            value += 0.08
            reasons.append("line trails off")
        if sentence_continues_after(episode, ending) or speaker_continues(episode, ending):
            value -= 0.15
            reasons.append("the same speaker carries straight on, so the thought is not finished")
        if RESOLVING.search(text):
            value -= 0.35
            reasons.append("final line closes the story beat")
        if level < 0.3:
            value -= 0.15
            reasons.append("soft delivery on the final line")
    elif ARRIVAL.search(ending.text):
        value += 0.35
        reasons.append("ends on someone arriving")
    elif is_physical_event(ending):
        value += 0.3
        reasons.append("ends on a physical event")
    else:
        value += 0.05
    landed = reaction_after(episode, ending)
    if landed:
        value += 0.15 * landed
        reasons.append("the script shows this moment landing on someone")
    if ending.kind == DIALOGUE and silence_after(episode, ending) >= 2.5:
        value += 0.08
        reasons.append("the script holds on this moment")
    return SignalScore(clamp(value), reasons)


def understanding_signal(episode: Episode, clip: Clip) -> SignalScore:
    """A rough guess at whether a new viewer could follow this, from spoken words only."""
    inside = cues_in_range(episode, clip.start, clip.end)
    lines = [cue for cue in inside if cue.kind == DIALOGUE]
    spoken = " ".join(cue.text for cue in lines)
    reasons: list[str] = []
    value = 0.35

    relationships = {match.lower() for match in RELATIONSHIPS.findall(spoken)}
    value += 0.3 * clamp(len(relationships) / 3)
    if relationships:
        reasons.append("relationship words spoken: " + ", ".join(sorted(relationships)[:5]))
    stakes = {match.lower() for match in STAKES.findall(spoken)}
    value += 0.2 * clamp(len(stakes) / 2)
    if stakes:
        reasons.append("stakes spoken: " + ", ".join(sorted(stakes)[:4]))
    if len(word_list(spoken)) >= 40:
        value += 0.1

    # Names of people who never speak here make a new viewer ask "who is that?"
    speakers = {word for cue in lines for word in word_list(cue.speaker or "")}
    pack_names = known_names_for(episode)
    absent = {word for word in word_list(spoken) if word in pack_names and word not in speakers}
    if absent:
        value -= min(0.25, 0.08 * len(absent))
        reasons.append("mentions people not in the clip: " + ", ".join(sorted(absent)[:3]))
    past = PAST_REFERENCE.findall(spoken)
    if past:
        value -= min(0.15, 0.05 * len(past))
        reasons.append("refers back to past events")
    first = first_story_cue(episode, clip.start, clip.end, known_names_for(episode))
    if first is not None and first.kind == DIALOGUE and CONTEXT_DEPENDENT_OPENING.match(first.text):
        value -= 0.1
        reasons.append("opening depends on what came before")
    return SignalScore(clamp(value), reasons)


def emotion_signal(episode: Episode, clip: Clip) -> SignalScore:
    inside = cues_in_range(episode, clip.start, clip.end)
    lines = [cue for cue in inside if cue.kind == DIALOGUE]
    reasons: list[str] = []
    if not lines:
        physical = sum(1 for cue in inside if is_physical_event(cue))
        return SignalScore(clamp(0.2 + 0.15 * physical), ["no dialogue"])
    mean_level = sum(delivery_level(cue) for cue in lines) / len(lines)
    turns = sum(1 for a, b in zip(lines, lines[1:]) if a.speaker != b.speaker)
    turn_rate = turns / max(clip.duration, 1.0) * 10
    physical = sum(1 for cue in inside if is_physical_event(cue))
    value = 0.55 * mean_level + 0.25 * clamp(turn_rate / 3) + 0.2 * clamp(physical / 2)
    if turn_rate >= 2:
        reasons.append("fast back and forth")
    if physical:
        reasons.append(f"{physical} physical event(s)")
    if mean_level >= 0.7:
        reasons.append("intense delivery throughout")
    return SignalScore(clamp(value), reasons)


def continuity_signal(episode: Episode, clip: Clip) -> SignalScore:
    """Lower when the clip jumps between places, since that is harder to follow cold."""
    inside = cues_in_range(episode, clip.start, clip.end)
    scene_numbers = sorted({cue.scene for cue in inside if cue.scene is not None})
    if len(scene_numbers) <= 1:
        return SignalScore(1.0, ["one scene"])
    scenes = {scene.number: scene for scene in episode.scenes}
    jumps = 0
    for number in scene_numbers[1:]:
        heading = (scenes[number].heading or "").upper() if number in scenes else ""
        if "CONTINUOUS" not in heading:
            jumps += 1
    if jumps:
        return SignalScore(0.25, [f"{jumps} jump(s) to an unconnected scene"])
    return SignalScore(0.7, ["moves through connected scenes"])


def duration_signal(clip: Clip) -> SignalScore:
    """All 20 to 60 second clips are valid. This only gives a preference for tighter ones."""
    seconds = clip.duration
    if 25 <= seconds <= 45:
        return SignalScore(1.0, [])
    if 45 < seconds <= 52:
        return SignalScore(0.7, [])
    return SignalScore(0.4, [f"{seconds:.0f}s is near the limit"])


def ad_risk_warnings(episode: Episode, clip: Clip) -> list[str]:
    """Flag content a human should check against ad platform rules. This is not a ranking input."""
    inside = cues_in_range(episode, clip.start, clip.end)
    text = " ".join(cue.text for cue in inside)
    warnings = []
    if ADULT_CONTENT.search(text):
        warnings.append("Possible sexual content. Check ad platform rules before using as a paid ad.")
    if GRAPHIC_CONTENT.search(text):
        warnings.append("Possible graphic content. Check ad platform rules before using as a paid ad.")
    return warnings


def spoiler_position_penalty(episode_number: int, last_episode: int) -> float:
    """Basic mode cannot read for spoilers, so it uses story position as a crude stand in.

    No penalty for the first 60 percent of the pack, rising to 10 points at the end.
    """
    if last_episode <= 1:
        return 0.0
    position = (episode_number - 1) / (last_episode - 1)
    return round(max(0.0, position - 0.6) / 0.4 * 10, 2)


def meaningful_story_cues(episode: Episode) -> list[Cue]:
    names = known_names_for(episode)
    return [cue for cue in episode.cues if is_meaningful(cue, names)]
