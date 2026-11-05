# Design decisions

Why the main choices were made, what else was considered, and what limits remain. Decisions marked **(confirm)** were made by the AI developer and need the candidate's own review before being defended as theirs.

## Current status

- **Basic mode** has run on all 50 episodes, and its results are real.
- **AI assisted mode** is fully built and tested against a stand in server, but **has never run on a real model**, because no API key was available. Its quality is unknown. Anything below about the blind tests describes the design, not a measured result.

## 1. Models point at cues, and code owns the facts

Every cue in the screenplay gets an ID such as `E12_C0032`. A model can only return IDs. Python looks up the real times, builds the clip, and validates it.

- **Why:** a promo with a wrong timestamp is useless to an editor, and models do invent numbers. This removes that failure by design rather than trying to catch it afterwards.
- **Stronger still:** the finder's prompt holds no timestamps at all, and a test enforces this.
- **Alternative rejected:** asking the model for times and checking them later. Checking only catches times that do not exist, not times that are plausible but wrong.

## 2. Reject instead of forcing a clip to fit

If a hook and ending are 61 seconds apart, the pair is rejected. It is not trimmed to 60. The real pack has this exact case: a strong line and a strong ending 60.8 seconds apart.

- **Why:** cutting a second off an arbitrary line damages the moment. The brief asks for 20 to 60 seconds, and the honest answer is sometimes "this pair does not work".
- **Every rejection is recorded with its reason**, so nothing disappears quietly.

## 3. Cuts land on shot changes where possible

A clip's start and end move to the nearest shot change when one is very close (1 second before the hook, 1.5 seconds after the ending), but only if no other line is affected. Each move is recorded in `boundary_adjustments`.

- **Why:** this is what an editor would do, and it gives the ending a moment to land on a reaction.
- **Sentence check:** the scripts often split one sentence across two cues using "...". A cue boundary is not always a sentence boundary, so a clip cannot start partway through a sentence, and a clip ending partway through one gets a warning.
- **Action check:** a clip does not open partway through a physical action, because the viewer would see the flinch without the blow. The start steps back to where the action began, as long as the hook stays within 3 seconds.

## 4. The cold viewer test hides what a viewer cannot know

This is the most important quality decision in the project.

The script contains information no viewer has. Speaker labels can state a relationship outright, for example a label naming someone as a former partner or as another character's parent. A model reading those labels would "understand" clips that a real viewer could not follow, and the test would pass everything.

So the blind test replaces speakers with SPEAKER A, SPEAKER B and so on, removes acting notes, and removes production words such as "cliffhanger". Spoken dialogue stays exactly as written, because a viewer hears it. A scan of 257 real clips found no character names left in the action and camera text.

- **Evidence must be real:** the blind viewer must quote lines supporting its answer, and code checks those lines exist in the clip. Invented evidence fails the test.
- **Known limit:** action text can still hold words like "her father". These are not rewritten.

## 5. The hook test only sees the first three seconds

A scrolling viewer decides from those seconds alone, so the judge gets only what begins in them. A judge who has read the whole clip would rate an opening higher because they know where it goes.

- **Hard rule:** only a rating of 4 or 5 out of 5 counts as strong. Starting on a dialogue cue proves nothing about whether it is interesting.

## 6. Different models find and judge

The finder and the evaluator should be different models, so a model is not approving its own picks. Blind prompts are never told who suggested a clip, why, or how it scored. If one model is used for both roles, the run records a warning.

## 7. Gates before scores

A promo needs a strong hook AND a strong ending AND must make sense alone. Adding scores together lets a strong part hide a weak part. This happened in the first Basic version (see `DEVLOG.md`). So in AI assisted mode a clip must pass every gate first, and only then is it scored. Basic mode has floors in the same spirit: hook and ending parts must reach 50 and understanding 40, and the final score, after the variety penalty, must reach 60.

These floors are why some good moments are missed. It is a deliberate trade: a short list of mostly usable clips is more useful to an editor than a long list to sift through. The cost is measured in `FAILURE_ANALYSIS.md`.

## 8. Scoring weights **(confirm)**

| Part | Weight | Why |
|---|---:|---|
| Hook | 30% | One of the brief's three requirements |
| Ending | 30% | Equal to the hook, because each is wasted without the other |
| Understanding | 20% | Lower only because it is also a pass or fail gate |
| Emotion | 10% | Supports the promo but is not a stated requirement |
| Continuity | 5% | Avoids clips that jump between unrelated places |
| Duration | 5% | Small preference for 25 to 50 seconds. All of 20 to 60 is valid |

Spoiler risk subtracts 5 (medium) or 15 (high) points. Each clip already chosen subtracts 8 from clips in the same episode and 4 from the next episode, capped at 12, so the list does not repeat one stretch of story.

A worked example: hook 100, ending 75, understanding 75, emotion 75, continuity 100, duration 100 gives 30 + 22.5 + 15 + 7.5 + 5 + 5 = 85.

Basic mode uses a slightly different mix, because its parts are clues and not judgements: hook 25%, ending 25%, understanding 15%, key moment 10%, emotion 10%, duration 10%, continuity 5%. Key moment is how much of the writer's own episode summary a clip covers.

**The score only compares clips. It is not a probability of an ad working.** These weights are judgement calls, and no performance data exists to tune them.

## 9. Duplicates

Two clips in one episode count as the same promo when they share at least half their combined time, or use the same hook or the same ending. The stronger one stays, and the removal is recorded.

Half was chosen because two 40 second clips sharing 30 seconds (30 / 50 = 0.6) feel like one promo, while sharing 15 seconds (15 / 65 = 0.23) do not.

There is one more rule. If at least 70% of a shorter clip sits inside a longer one, they are also the same promo. A 30 second clip sharing 28 seconds with a 58 second clip scores only 28 / 60 = 0.47 on the first rule, yet it is clearly the same moment. This case was found in real output.

## 10. First post recommendation

The top ranked clip is not automatically the right first post. A shocking later scene can work well once viewers know the show, but the first promo must also explain the premise. So the first post is the highest ranked clip rated at least 4 of 5 for premise fit with low spoiler risk.

The show's title counts as part of the promise, so a clip confirming what the title already says is not treated as a spoiler. Only this check may see the story outline.

## 11. Choosing a model provider

Checked against official pages on 2026-11-05. Confirm in your own console, since these change.

| Provider | Free option | Trains on inputs? | Decision |
|---|---|---|---|
| Google Gemini free tier | Yes | **Yes.** Terms say content is used to improve products, human reviewers may read it, and "Do not submit sensitive, confidential, or personal information to the Unpaid Services" | **Rejected for this pack.** It conflicts with the confidentiality rule. The paid tier is not used for improvement and is an option |
| Groq | Yes | **No.** Services Agreement section 4.2: "Groq is not permitted to use Inputs or Outputs for training or fine-tuning" (page last modified June 22, 2026). Inference data is not retained by default. Logs may be kept up to 30 days for reliability, and Zero Data Retention can be turned on | **Chosen.** One free key gives two different model families |
| Cerebras | $5 credit, card required, expires in 30 days | Privacy policy says inputs and outputs are not retained, but no explicit no training statement was found | Not chosen |
| Mistral free plan | Yes | Only third party pages were found. They say training is on by default, with an opt out | Not chosen. Not confirmed from Mistral's own pages |
| Local model (Ollama) | Yes | Nothing leaves the computer | Supported with no code change. Good for confidentiality, but likely weaker on 16 GB of memory and not tested here |

**Limits observed for the chosen plan (Groq):** the limits page lists 30 requests per minute, 1,000 requests per day, 8,000 tokens per minute and 200,000 tokens per day per model for `openai/gpt-oss-120b` and `qwen/qwen3.8-27b`. That page describes its table as Developer plan limits and has a separate Free plan tab, so check your own account.

**Open caveat:** Beta Services are treated differently in Groq's agreement, and `qwen/qwen3.8-27b` is not on the production models list that was checked. If that matters, use a production model as the evaluator. It is a one line change in `.env`.

## 12. One small client for every provider

Almost all providers offer an OpenAI compatible API, so one file handles all of them. Changing provider means changing `.env`. The brief says stronger models may be connected through provided APIs at interview, so this matters.

- **Alternative rejected:** a framework or one adapter per provider. That is more code to explain, for no benefit here.

## 13. Saving progress

Results are saved after every episode and every clip. Running the same command again skips finished work. If an episode's text or the model settings change, that work is redone. Long waits for a rate limit stop the run cleanly so it can resume later. A failed episode is recorded with its exact error and reported, never silently skipped.

## 14. Basic mode: signals, not understanding

Basic mode never claims understanding. Its hook and ending strengths always read `not_rated`, and its cold viewer result reads `not_performed`. It relies on structure more than word lists:

| Signal | What it uses | Why it is useful |
|---|---|---|
| Final beat | The last line or last action of an episode | Writers place their cliffhangers there on purpose |
| Next episode's notes | Whether the following episode's continuity note describes a cliffhanger, climax or revelation | The writers' own statement about their story. It only ever confirms a final beat |
| Reaction | An intense reply from someone else, or a described reaction, right after a moment | Shows the moment landed |
| Acting notes | The delivery written beside each line | A human written record of intensity |
| Pause | Silence before or after a line | A new exchange starting, or the script holding on a moment |
| Summary overlap | How much of the writer's episode summary the clip covers, scaled to clip length | The nearest thing Basic has to knowing what matters |
| Pace | How often speakers change | Fast back and forth suggests conflict |
| Word lists | Stakes, threats, relationships, physical events | Capped, so they are never the whole score |

**Why "cliffhanger" in the next episode's notes is treated differently from a sound cue.** A sound cue describing a "cliffhanger sting" describes music. A continuity note saying a story picks up from a cliffhanger describes the plot, written by the people who plotted it. Even so, it can mislead: see clip B0013 in `FAILURE_ANALYSIS.md`.

**How it was improved.** Basic started as a simple baseline. Once no API key was available, it became the only source of real results, so it was improved by reading its mistakes. To keep that honest, half of the AI prepared reference set was held back during the changes. Matches went from 4 of 16 with 25 clips to 5 of 16 with 19 clips, including 3 of the 8 held back. Small bug fixes came after that measurement, and they did not change these counts. The set was written by the same AI that built the tool, so treat these numbers as a rough check only.

## 15. What the data showed

All 50 files were read. The pack has 3,727 cues in 100 scenes, about 103 minutes in total.

| Observation to verify | What was found |
|---|---|
| One episode may have a different scene ending pattern | Confirmed as a label casing difference only (`SCENE END:` in place of `Scene end:`) in one episode. It parses the same |
| Character names appear in different forms | Confirmed, and worse than expected. See below |
| Some sound descriptions use the word "cliffhanger" | Confirmed: 5 sound cues, plus 9 camera or action cues. None of them affects any score, and tests enforce this |
| Timing problems | 20 small overlaps within a track and 1 cue slightly past its scene end. All recorded, none removed |

**Label traps:**
- One generic label refers to at least two different people in different episodes.
- Another generic label refers to a main villain in one episode and an unnamed guest in another.
- One character has different labels across two consecutive episodes.

So labels are never merged across episodes. Inside one clip, a titled label joins a bare name only when both exist, such as LADY ANNA and ANNA. LORD GREY and LADY GREY stay separate.

**Worth telling the show's team:** the family estate's name changes spelling across many episodes, as does the hero's surname. This is the sort of problem that would become visible if clips from different episodes were joined, which is one more reason not to do that in Version 1.

**Ad suitability:** one late episode has a sexual scene, and some scenes have strong violence. A clip can be dramatically strong and still break ad platform rules, so such clips carry a warning for a person to check.

## 16. Not built, on purpose

- **Two segment and cross episode promos.** Single clips were the priority. The output format already allows two segments, but nothing generates them yet.
- **Learning from real ad results.** There is no data. See below.

## 17. Cost and scale

**Measured so far:** Basic mode took 1.1 seconds for all 50 episodes, with no model calls and no cost.

**Estimated for AI assisted mode, not measured:** using prompt sizes from the real pack, at about 4 characters per token, and assuming how long replies would be, one run on a 50 episode show would use about 210,000 to 330,000 tokens. At the listed Groq price for `openai/gpt-oss-120b` ($0.15 input and $0.60 output per million tokens, checked 2026-11-05), that is about 6 to 9 US cents per show if every role used that model. At the free plan's pace it would take about 30 to 50 minutes. Models that reason first may use more tokens than this estimate.

At that level, cost is not the limit at real volume. The real limits are review time and rate limits. A person should still approve each promo, so the tool's job is to shorten what they look through, and to record why it chose each clip.

## 18. How to know this works in production

The current checks show the output is valid and that blind judges find it strong. They do not show it sells. The real test is whether clips picked by this tool earn more watch time and more episode starts than an editor's picks, measured with a simple split test. Those results could then replace the guessed weights in section 8.
