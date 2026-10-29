# Research, strategy and usability testing

## Honesty first
You can't interview users. What you can do is **frame hypotheses** and **design the study** someone will run. Label everything:
- **Evidence**: the user told you, or it's in real data (analytics, support tickets, comments, recordings) that you actually read.
- **Assumption**: your inference. It goes in the contract's "to validate" list with a test.

Never write "users want…" without evidence. Write "we assume users want… (validate by…)".

## Product strategy in five questions
1. Who has the problem, and how do they solve it today?
2. Why is today's way painful (time, money, risk, emotion)?
3. What's the smallest thing that would make their life clearly better?
4. How will we know it worked (one metric, one observable behaviour)?
5. What are we deliberately **not** doing?

## Jobs to be done
"When <situation>, I want to <motivation>, so I can <outcome>." Write one per core journey. Design screens for the job, not for the persona's demographics.

## Picking a research method
| Need | Method | Smallest useful version |
|---|---|---|
| Understand the problem | Interviews | 5 people, 30 min, open questions about the last time it happened |
| Find where a flow breaks | Usability test | 5 people, 3–5 tasks, think-aloud |
| Choose between two designs | Preference + task success | A/B with real tasks, not "which looks nicer" |
| Know how many / how often | Analytics, survey | Instrument the event before shipping |
| Information architecture | Card sort / tree test | 15+ people, online |

## Usability test plan (to hand to the owner)
- Goal: what decision this test informs.
- Participants: who, and how many (5 per segment).
- Tasks: realistic, with a start state and a success definition, no UI words in the prompt ("You want to send this video to your sister", not "Click Share").
- Measure: task success, time, errors, where they hesitated, what they said.
- After: a short severity-ranked list (blocker / major / minor), each with a proposed fix.

## Heuristic review (what you *can* do yourself)
Walk the journey against Nielsen's 10 heuristics: visibility of status, match with the real world, user control, consistency, error prevention, recognition over recall, flexibility, minimal design, error recovery, help. Report findings as "heuristic review, not user-tested".
