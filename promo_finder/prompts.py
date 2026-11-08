"""All model prompts live here, each with a version.

Changing a prompt means changing its version, which automatically makes the cache
ask again instead of reusing answers to the old prompt.

Three separate questions go to the models:
  FINDER      reads an episode and points at cue IDs. Never sees a timestamp.
  HOOK TEST   sees only the first three seconds, and knows nothing else.
  COLD VIEWER sees only the clip with names hidden, and knows nothing else.
  FINALIST    sees the story outline, only to judge spoilers and premise fit.

The evaluator prompts are never told who suggested a clip, why, or how it scored.
"""

from __future__ import annotations

from .boundaries import word_list
from .parser import ACTION, DIALOGUE, Cue, Episode

FINDER_VERSION = "finder_v1"
HOOK_VERSION = "hook_v1"
COLD_VIEWER_VERSION = "cold_viewer_v1"
FINALIST_VERSION = "finalist_v2"  # v2: outline only up to the latest episode in each batch

FINDER_SYSTEM = (
    "You help a promo editor at a short drama company. Promos are short clips posted on Instagram, TikTok and "
    "YouTube to pull in viewers who have never seen the show. You read one episode's screenplay and point at cue "
    "IDs. You never give times, because software reads the times from the screenplay. Reply with one JSON object "
    "and nothing else."
)

FINDER_TEMPLATE = """SHOW TITLE: {title}
EPISODE: {number}
SUMMARY, for your understanding only: {logline}

CUES. Each row is: cue id | type | speaker | text
{rows}

TASK
Find moments in this episode that could open or end a promo of 20 to 60 seconds, which is usually about 8 to 25 lines of dialogue.

hook_events are moments that could be the very first thing a scrolling viewer sees.
A good hook is a physical shock, an accusation, a reveal, a threat, a betrayal, or a line so sharp that someone stops. It must grab a person who knows nothing about the show.
These are not hooks: calm conversation, a bare name called out, a reply like "Yes", a line that continues an earlier sentence, or a description of scenery.

ending_events are moments a clip could stop on, leaving the viewer needing to know what happens next.
A good ending leaves one specific question open: someone is about to reveal a secret, a betrayal is discovered, an accusation lands, a person unexpectedly appears, a threat is made.
These are not endings: a moment that settles the conflict, an ordinary question nobody cares about, or a line that only sounds dramatic because it contains a dramatic word.

RULES
- Use only cue IDs from the list above. Only LINE and ACTION rows can be chosen.
- Up to 5 hook_events and up to 5 ending_events. Return fewer, or none, if the episode has nothing strong. Do not force it.
- "quote" is the first few words copied exactly from that cue.
- "strength" is a whole number from 1 to 5. Use 5 rarely. 3 means ordinary.
- Do not give times, durations or timestamps.

Reply with this JSON shape:
{{
  "hook_events": [{{"cue_id": "", "quote": "", "event": "what happens, in a few words", "why": "why a stranger would stop", "strength": 3}}],
  "ending_events": [{{"cue_id": "", "quote": "", "event": "what happens, in a few words", "open_question": "what the viewer now needs to know", "strength": 3}}]
}}"""

HOOK_SYSTEM = (
    "You are an ordinary person scrolling TikTok who is hard to impress. You know nothing about any show. "
    "Reply with one JSON object and nothing else."
)

HOOK_TEMPLATE = """Below is everything that happens in the first three seconds of a video.
SPEAKER A, SPEAKER B and so on are people on screen. Rows marked SHOT describe how it is filmed. A shot by itself, such as a wide view of a garden, is not an event.

{rows}

Would you stop scrolling to see what happens? Rate from 1 to 5:
1 = keep scrolling, nothing is happening
2 = mildly interesting, I would still scroll
3 = I might pause, but I have no strong reason to stay
4 = I would stop, something shocking, hostile or strange is clearly happening
5 = impossible to scroll past. Use this rarely.

Judge what is actually said and done. A dramatic word in an ordinary sentence does not count. A line that needs earlier context to mean anything does not count.

Reply with this JSON shape:
{{"what_grabs_attention": "", "what_is_missing": "", "rating": 1}}"""

COLD_VIEWER_SYSTEM = (
    "You have never heard of this show. You have just watched one short clip on your phone, and you know only what "
    "the clip shows. Never fill a gap with a guess. If the clip does not state or clearly show something, say "
    "\"unclear\". Reply with one JSON object and nothing else."
)

COLD_VIEWER_TEMPLATE = """Below is the whole clip, in order.
SPEAKER A, SPEAKER B and so on are people on screen. You only know a person's name if someone says it aloud. Rows marked SHOT, ACTION and SOUND describe what you see and hear.

{rows}

Answer only from this clip.

who_appears_involved: who seems to be involved, described only as the clip allows.
what_is_happening: what is going on, in one sentence.
main_conflict: the central conflict in one sentence, or "unclear".
wants_to_know_next: the specific question this clip leaves you with, or "unclear".
evidence_lines: 1 to 3 lines copied exactly from the clip that show the conflict.
missing_context: what would confuse someone who sees only this clip. Say "nothing" if nothing would.
conflict_understood: true only if you could explain the conflict to a friend from this clip alone.
question_understood: true only if the clip leaves a specific unanswered question.
clarity_rating: from 1 to 5, how clearly the situation comes across. 5 means anyone would follow it at once. 1 means it makes no sense alone.
ending_rating: from 1 to 5, how badly you need to know what happens next.
  1 = I do not care
  2 = the moment is settled, or it just stops
  3 = mildly curious
  4 = I would look for the next part
  5 = I must find out. Use this rarely.
  An ordinary question is not suspense. A moment that settles the conflict scores 2 or lower.
ending_resolves_conflict: true if the end settles the main conflict in this clip.
emotional_impact: from 1 to 5, how strongly this makes you feel something.
plays_as_one_moment: from 1 to 5, whether this feels like one complete piece and not random pieces.

Reply with this JSON shape:
{{"who_appears_involved": "", "what_is_happening": "", "main_conflict": "", "wants_to_know_next": "", "evidence_lines": [""], "missing_context": "", "conflict_understood": false, "question_understood": false, "clarity_rating": 1, "ending_rating": 1, "ending_resolves_conflict": false, "emotional_impact": 1, "plays_as_one_moment": 1}}"""

FINALIST_SYSTEM = (
    "You review promo clips for a drama series, and you know the full story outline. Promos are shown to people who "
    "have not started the show. Reply with one JSON object and nothing else."
)

FINALIST_TEMPLATE = """SHOW TITLE: {title}

STORY OUTLINE, by episode:
{outline}

CLIPS TO REVIEW. Each has a clip_key, its episode, and the spoken lines in order.
{clips}

For each clip give:
spoiler_risk: "low" if it holds back the story's later turns, "medium" if it gives away a real turn, "high" if it reveals how a major conflict ends. The promise made by the show's title is not a spoiler.
what_it_gives_away: a few words.
premise_fit: from 1 to 5, how well this clip introduces the show's central idea to someone deciding whether to start at Episode 1. 5 means the clip is the premise. 1 means it only makes sense as a later plot detail.
premise_reason: a few words.
ad_platform_risk: "low", "medium" or "high", for how likely a paid ad of this clip is to hit platform rules on sexual content or graphic violence.
ad_platform_reason: a few words.

Reply with this JSON shape:
{{"clips": [{{"clip_key": "", "spoiler_risk": "low", "what_it_gives_away": "", "premise_fit": 1, "premise_reason": "", "ad_platform_risk": "low", "ad_platform_reason": ""}}]}}"""


def finder_row(cue: Cue) -> str:
    """One cue as the finder sees it. There is deliberately no time in this row."""
    kind = "LINE" if cue.kind == DIALOGUE else "ACTION"
    speaker = cue.speaker if cue.kind == DIALOGUE else "-"
    return f"{cue.cue_id} | {kind} | {speaker} | {cue.text}"


def finder_cues(episode: Episode) -> list[Cue]:
    return [cue for cue in episode.cues if cue.kind in (DIALOGUE, ACTION) and cue.has_valid_time and word_list(cue.text)]


def build_finder_prompt(episode: Episode, title: str) -> str:
    rows = "\n".join(finder_row(cue) for cue in finder_cues(episode))
    return FINDER_TEMPLATE.format(title=title, number=episode.number, logline=episode.logline, rows=rows)


def build_hook_prompt(rows: str) -> str:
    return HOOK_TEMPLATE.format(rows=rows)


def build_cold_viewer_prompt(rows: str) -> str:
    return COLD_VIEWER_TEMPLATE.format(rows=rows)


def build_outline(episodes: list[Episode], up_to_episode: int) -> str:
    """Episode summaries from the start of the show up to and including `up_to_episode`.

    A clip can only show events up to its own episode, so later summaries are not needed to
    judge what it gives away, and leaving them out sends less of the story to the provider.
    The cost: the reviewer cannot see a turn that later episodes reverse or pay off.
    The closing note stops the reviewer reading the last summary shown as the end of the story.
    """
    shown = sorted((episode for episode in episodes if episode.number <= up_to_episode), key=lambda e: e.number)
    lines = [f"E{episode.number}: {episode.logline}" for episode in shown]
    if any(episode.number > up_to_episode for episode in episodes):
        lines.append(f"(The outline stops at Episode {up_to_episode}. The story continues after it, "
                     "but later episodes are deliberately not shown.)")
    return "\n".join(lines)


def build_finalist_prompt(title: str, outline: str, clips_text: str) -> str:
    return FINALIST_TEMPLATE.format(title=title, outline=outline, clips=clips_text)
