# Failure analysis

Where the tool picks badly, using actual cue IDs and times from the final run on the 50 episode pack.

**Who made these judgements:** Claude Code, acting as an AI reviewer. It has read the whole show, so it is not a cold viewer, and it also wrote the tool, so it is not independent. No human has reviewed these clips. The candidate should confirm or change them.

**What is covered:** Basic mode only. AI assisted mode has never run on a real model, so nothing can be said about how it would choose. This file uses cue IDs and general descriptions, and holds no script text. A private copy with the script lines is in the raw outputs.

## Summary

| Reviewer verdict | All 19 clips | Top 10 |
|---|---:|---:|
| Good | 9 | 4 |
| Middling | 5 | 4 |
| Weak | 5 | 2 |

Against a separate AI prepared set of 16 moments, Basic mode matched 5 and missed 11.

**The main pattern: Basic mode favours loud over quietly menacing, and wordy over visual.** It reads acting notes and words. It cannot tell that a calm line is terrifying, or that a clip with few words is clear on screen.

## A. Weak selections

### B0009: gives away too much
- **Episode and time:** 45, 00:54.00 to 01:53.20 (59.2s)
- **Cues:** hook `E45_C0040`, ending `E45_C0070`
- **Why the tool selected it:** hook part 92 (accusation wording, intense delivery) and ending part 100 (the episode's final beat, confirmed by the next episode's notes).
- **Why it is weak:** it comes from late in the story and tells a new viewer how major conflicts turned out. The opening line also depends on earlier events.
- **Better choice:** keep the strong ending and cut the rest. `E45_C0060` to `E45_C0070` (01:26.50 to 01:53.20, 26.7s) is a valid clip that gives away less.
- **How to improve:** Basic's only spoiler check is story position, worth just 7 points here. The AI assisted spoiler review is designed for this, but is untested.

### B0013: the ending settles the question
- **Episode and time:** 13, 00:53.50 to 01:52.00 (58.5s)
- **Cues:** hook `E13_C0036`, ending `E13_C0070`
- **Why the tool selected it:** ending part 96. It is the final beat, a physical event, and the next episode's notes call it an open moment.
- **Why it is weak:** the clip stops when she finds what she was searching for. Viewers see a win, not an open question. **The writers' note misled the tool:** the story continues from here, but this clip's own tension is over.
- **Better choice:** stop while she is still searching. `E13_C0036` to `E13_C0066` (00:53.50 to 01:43.00, 49.5s) is valid.
- **How to improve:** treat "finds" or "reaches" actions as closing a beat. The AI assisted gate on resolved endings targets this, but is untested.

### B0014: opens on a reply, and spoils a late turn
- **Episode and time:** 43, 00:00.00 to 00:21.80 (21.8s)
- **Cues:** hook `E43_C0002`, ending `E43_C0019`
- **Why the tool selected it:** it covers most of the episode's summary (key moment part 97) and has a physical event in the opening seconds.
- **Why it is weak:** the first line answers something from the previous episode, which the viewer never saw. It also reveals a late turn in the story.
- **Better choice:** none known for a new viewer. Keep it for later posts.
- **How to improve:** this exposed a real gap. The reply check looks at the previous line, but an episode's first line has none, even when the scene continues from the last episode. Such openers should count as possible replies.

### B0018: weak opening, and it jumps between places
- **Episode and time:** 20, 01:09.20 to 01:49.50 (40.3s)
- **Cues:** hook `E20_C0042`, ending `E20_C0067`
- **Why the tool selected it:** a strong final beat. The hook part (55) just cleared its floor because of the acting note.
- **Why it is weak:** the opening line would not stop a scroll. The clip then jumps to an unrelated place. The tool rated this as connected because the heading says CONTINUOUS, which means "at the same moment", not "in the same place".
- **Better choice:** the single location scene `E20_C0015` to `E20_C0034` (00:21.30 to 00:56.50, 35.2s) is valid, though not clearly strong.
- **How to improve:** compare place names in scene headings as well as the word CONTINUOUS.

### B0006: hard to follow alone
- **Episode and time:** 29, 01:23.00 to 01:52.80 (29.8s)
- **Cues:** hook `E29_C0053`, ending `E29_C0071`
- **Why the tool selected it:** a physical opening, plus a final beat with threatening wording.
- **Why it is weak:** after the opening it is mostly one person alone, naming objects and a person the viewer has never heard of. It ends on a vow, not an event.
- **Better choice:** the earlier exchange `E29_C0022` to `E29_C0048` (00:37.40 to 01:18.50, 41.1s) is valid and states its stakes aloud.
- **How to improve:** the understanding signal should mark down unexplained names and objects. A blind cold viewer test is the proper check, and is untested.

## B. Middling selections

| Clip | Episode and time | Cues | Problem | Better choice |
|---|---|---|---|---|
| B0002 | 34, 00:33.20 to 01:15.80 | `E34_C0017` to `E34_C0043` | A decent scene, but not the episode's peak | `E34_C0091` to `E34_C0114` (02:22.20 to 03:04.50). This passed every floor with a score of 63, but lost to earlier clips on score |
| B0005 | 24, 00:32.50 to 01:03.80 | `E24_C0028` to `E24_C0046` | Ends on a humiliating line with no open question | `E24_C0024` to `E24_C0069` (00:32.50 to 01:29.80), which ends on a vow to return |
| B0007 | 21, 00:03.60 to 00:35.80 | `E21_C0005` to `E21_C0022` | A side story, and the next line settles it | `E21_C0058` to `E21_C0073` (01:19.80 to 01:48.50), which ends on the episode's reveal |
| B0010 | 27, 01:58.70 to 02:29.20 | `E27_C0075` to `E27_C0093` | Opens on a one word echo, mid exchange | `E27_C0066` to `E27_C0093` (01:47.80 to 02:29.20), which starts where the exchange starts |
| B0017 | 28, 00:37.70 to 01:15.30 | `E28_C0031` to `E28_C0056` | An ordinary taunting question mistaken for a cliffhanger | `E28_C0066` to `E28_C0087` (01:28.00 to 02:04.90), which ends on a real consequence |

## C. Good moments the tool missed

These come from the AI prepared reference set. Scoring each one with Basic's own signals shows the real reason it was missed. A floor is 50 for hook and ending, and 40 for understanding. A clip also needs a total of at least 60.

| Moment | Cues | Time | Score | Hook | Ending | Understand | What stopped it |
|---|---|---|---:|---:|---:|---:|---|
| A calm opening leads to a bombshell | `E01_C0008` to `E01_C0027` | 00:11.00 to 00:41.50 | 55 | 51 | 50 | 45 | Total just under the bar |
| A rescue from guards | `E03_C0047` to `E03_C0081` | 00:58.30 to 01:36.50 | 58 | 63 | 35 | 42 | Ending floor |
| A name is demanded, then doors burst open | `E27_C0004` to `E27_C0028` | 00:03.40 to 00:51.50 | 57 | 26 | 50 | 75 | Calm opening fails the hook floor |
| A quietly coerced witness | `E33_C0070` to `E33_C0092` | 01:53.80 to 02:36.20 | 54 | 26 | 53 | 70 | Quiet menace reads as a low hook |
| A refusal, then a sentence begins | `E34_C0091` to `E34_C0114` | 02:22.20 to 03:04.50 | 63 | 61 | 63 | 65 | Passed everything, lost on score |
| A vow to return | `E36_C0091` to `E36_C0119` | 02:25.80 to 03:16.80 | 55 | 20 | 62 | 90 | Short question as opening fails the hook floor |
| Paraded in chains, then an explosion | `E41_C0026` to `E41_C0052` | 00:41.00 to 01:33.50 | 46 | 36 | 70 | 55 | Hook floor |
| A visual transformation | `E39_C0040` to `E39_C0058` | 01:01.20 to 01:38.41 | 42 | 29 | 45 | 45 | Few words, so little to read |
| A threat is called out | `E32_C0013` to `E32_C0040` | 00:16.00 to 00:52.50 | 54 | 47 | 37 | 75 | Hook and ending floors |
| A fight that forces a name | `E16_C0014` to `E16_C0046` | 00:14.30 to 00:55.20 | 59 | 66 | 43 | 35 | Understanding reads words, not action |
| Running back into danger | `E18_C0032` to `E18_C0048` | 00:56.50 to 01:27.50 | 53 | 58 | 18 | 45 | Ending not recognised as a peak |

**Another result of this:** 32 of 50 episodes have no clip on the final list, and some of them clearly hold strong moments. A person relying only on this list would miss them.

## D. Correct rejections

These are cases where the tool was right to refuse.

| Case | Cues | What happened |
|---|---|---|
| Strong pair, just over the limit | `E36_C0085` to `E36_C0119` | 60.80 seconds, so rejected as too long. It was not trimmed, because a cut would damage the moment |
| One word opening | `E36_C0087` | Rejected as too slight to open a promo. This was an AI prepared pick, so the tool caught the reviewer's own mistake |
| Soft final beats | `E06_C0094`, `E08_C0062`, `E17_C0074` | All scored 0.23 against a 0.50 floor. These are warm, quiet endings, and they are not cliffhangers even though each ends an episode |
| A calm victory line | `E07_C0056` | Scored 0.23. The moment feels finished |
| A line that closes the story beat | `E14_C0005` | Scored 0.00, as the wording settles the question |
| The word "cliffhanger" in production text | `E01_C0094`, `E15_C0055`, `E16_C0064`, `E36_C0121`, `E37_C0079`, `E03_C0118`, `E20_C0068`, `E21_C0076`, `E22_C0081`, `E23_C0067`, `E26_C0051`, `E31_C0087`, `E32_C0117`, `E41_C0053` | None is used as an ending in the final list. Tests prove the word changes no score |
| Opening partway through a sentence | Example: `E03_C0069` | 73 pair attempts were rejected for this reason |

Across the run, 9,382 pairs were tried, 2,074 made valid clips, and 19 were recommended. The rest were rejected or fell below the bar, with counts in `processing_summary.json`.

**One honest note:** the episode with a sexual scene has no clip on the list, but this is not because the tool understood the problem. Content warnings are only flags for a person. They do not remove clips.

## E. Bugs this review found and fixed

| What the review showed | Cause | Fix |
|---|---|---|
| A near duplicate from one scene, on cues `E12_C0039` to `E12_C0055` | Shared time was under the duplicate rule, because it was measured against the longer clip | A short clip mostly inside a longer one now counts as a duplicate |
| A clip opened on a flinch after a blow, at `E24_C0026` | The start did not check for an action already in progress. The first fix also stepped back only once | The start now steps back through overlapping actions, and opens on `E24_C0024` |
| Clips drifted towards exactly 60 seconds | The summary overlap signal rewarded length | The signal is now scaled to clip length, with a preference for tighter clips |

## F. What to improve next, in order

1. **Run AI assisted mode on a real model.** Most failures above are exactly what its blind tests were built to catch, but that is still only a design claim.
2. Get human ratings on these clips, so the score can be checked against real judgement.
3. Mark success actions as closing a beat, and compare place names in scene headings.
4. Treat an episode's first line as a possible reply when it continues the previous episode.
5. Let quiet scenes through by also looking at how a whole exchange builds, and not only the first and last lines.
