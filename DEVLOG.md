# Development log

Real issues from building this project, with what caused them, what changed, and whether it was tested. Written by the AI developer (Claude Code). No show content appears here.

## Mistakes made by the AI tool

### First Basic scoring let weak endings through
- **What happened:** the first version recommended 91 clips. Reading the output showed a clip ranked 6th with a hook part of 90 and an ending part of 27, on a line that was no cliffhanger at all.
- **Cause:** the score simply added parts together, so a strong hook could hide a weak ending. The brief needs both.
- **Change:** added separate minimum levels for hook and ending, raised the minimum score, and gave more weight to an episode's final beat, where writers place their cliffhanger on purpose.
- **Tested:** yes. The list fell to 25 clips. Matches against the AI prepared reference fell from 9 of 16 to 4 of 16. The first run's files were overwritten by this change, so only these numbers remain from it.

### The first round of new signals added a new bias
- **What happened:** after adding a signal for how much of the episode summary a clip covers, clips drifted to exactly 60 seconds, and the list grew back to 41.
- **Cause:** a longer clip covers more words just by being longer. The AI tool added the signal without checking for this.
- **Change:** scaled the signal to clip length, and added a preference for tighter clips.
- **Tested:** yes, by reading the list and the spread of clip lengths. Clips now run from 21.8 to 60 seconds.

### A near duplicate passed the duplicate check
- **What happened:** two clips from one scene appeared in the list, ending one cue apart (cues in Episode 12).
- **Cause:** the check compared shared time with the total time of both clips. A short clip inside a long one scores low on that measure.
- **Change:** a clip with 70% of its time inside another now counts as a duplicate.
- **Tested:** yes, `test_short_clip_inside_a_longer_one_counts_as_a_duplicate`, and the clip is gone from the real output.

### A fix that did not fix the problem
- **What happened:** one clip opened on someone flinching, just after the blow that caused it. The first fix moved the start back one step and reported success, but that only reached the flinch, because the blow overlapped it.
- **Cause:** the fix was written and assumed to work. The problem was only noticed on reading the real times.
- **Change:** the start now keeps stepping back through overlapping actions.
- **Tested:** yes, `test_start_steps_back_through_overlapping_actions_to_the_cause`, and the real clip now opens on the blow.

### A floor was stricter than its evidence allowed
- **What happened:** an understanding floor of 50 failed clear visual moments.
- **Cause:** that signal only reads spoken words, so action heavy clips score low whatever they show.
- **Change:** lowered the floor to 40. It still misses action clips, and this is listed as a known failure.
- **Tested:** yes, on the real pack.

### Real character names written into public code comments
- **What happened:** code comments in the parser and masking files used real character labels as examples.
- **Cause:** the examples were copied from the data while it was on screen, ignoring that this code is meant to be publishable.
- **Change:** replaced them with invented names and built `tools/check_confidentiality.py`.
- **Tested:** yes. The scan now passes, and tests plant leaks to prove it finds them.

### The confidentiality scanner had a bug that hid text
- **What happened:** the first version reported the code as clean while skipping large parts of it.
- **Cause:** it reused a helper that removes `[bracketed]` stage notes, and in Python files that removed every list, including the invented sample script.
- **Change:** the scanner now has its own plain word reader. It also caught one invented sample line that happened to echo a real one, so that line was reworded.
- **Tested:** yes. `tests/test_confidentiality_scan.py` plants a line inside a Python list.

### An AI prepared reference pick was a bad hook
- **What happened:** one pick opened on a one word line. The boundary engine rejected it as too slight to open a promo.
- **Cause:** the pick was chosen for the ending, without looking closely at the opening line.
- **Change:** the stronger line just before it makes a 60.8 second clip, which is correctly rejected as too long, so the pick moved to a later line. Trimming was not used.
- **Tested:** yes, on the real pack. This is a real example of the brief's "68 seconds apart" situation.

### Two tests expected the wrong thing
- **What happened:** two new tests failed on the first run.
- **Cause:** the tests were wrong, not the code. One expected a clip to move back 4 seconds, which breaks the 3 second rule. The other used a pair that really is 19 seconds long.
- **Change:** corrected the tests, and split the first into a "moves back" case and a "rejects" case.
- **Tested:** yes.

## Decision: finishing without an API key

The candidate chose not to add a key. So AI assisted mode remains built and tested against a stand in server, but unrun on a real model. This changed the priorities:

- Basic mode became the only source of real results, so it was improved using its own mistakes. Earlier versions of its results were kept in the raw outputs to show the change.
- Half of the AI prepared reference set was held back during those changes.
- A real HTTP test was added, because a first real run at interview would otherwise be the first time that code had touched a network.
- Replies cut off by the output limit are now asked again with more room, a known risk with models that reason first. This is untested on a real model.

## Other findings

### The obvious free model was the wrong choice
Gemini's free tier looked like the natural default. Its terms say not to submit confidential information and that human reviewers may read inputs, which conflicts with the pack's confidentiality rule. Groq was chosen instead. See `DESIGN_DECISIONS.md`.

### The interface was listening on the network
Streamlit listens on all network addresses by default, and its startup message showed a public address. Uploaded scripts are confidential, so `.streamlit/config.toml` now limits it to this computer.

### The app's preview tool could not open the Desktop folder
macOS privacy rules stopped the desktop app's preview launcher from reading the project. The server was started from a shell instead, and the preview attached to it.

### The home folder is a git repository
This project sits inside a git repository rooted at the home folder. A careless `git add` there could have included the scripts. The prototype now has its own separate repository, and private material sits outside it and is ignored at both levels.

### The cold viewer test would have been too easy
Reading the scripts showed that speaker labels state relationships a viewer cannot know. Without masking, the test would pass clips real viewers could not follow. This led to the blind transcript. See `DESIGN_DECISIONS.md`, section 4.

### Token budget shaped the evaluator
A real estimate gave about 1,800 tokens per clip for the blind tests, close to the free daily limit. A clip with a weak hook cannot pass anyway, so the longer cold viewer call is now skipped for those clips. Comparisons between modes still run both tests on every clip.

## Decisions awaiting the candidate

- Scoring weights and rating cut offs.
- Whether the first post recommendation is actually the clip they would post.
- All human ratings, which are still blank.
- The manual reference set, which is still blank, so no human comparison exists.
- The AI reviewer's verdicts in `FAILURE_ANALYSIS.md`.
