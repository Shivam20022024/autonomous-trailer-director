# AI collaboration log

## Phase 1: first prototype (Gemini / Claude assistant)

- An AI assistant was asked for a two-agent design that keeps generation separate from validation, Pydantic schemas based on the assignment's JSON example, and pytest tests for the verifier.
- A `MockLLM` class was written first so the retry loop could be tested without API credits.
- An AI suggestion to put the entire constraint list into one large prompt was rejected in favour of a rule-based verifier.

## Phase 2: review and rebuild (Claude Code, Claude Opus 5.5)

### How the work was delegated
1. **Audit before building.** Claude Code was asked to analyse the prototype, then to compare it against the assignment brief. It ran the code and probed the verifier directly instead of only reading it.
2. **Plan approval.** Claude proposed a prioritised plan (data, maps, verifier rewrite, planner, change handling, tests and docs). It was approved before any code was written.
3. **Implementation.** Claude wrote the sample data, the replay responses, all modules, the tests (55 at the end) and the docs. The original prototype was backed up before being replaced.

### How AI output was checked
- **Direct probes of the verifier.** Hand-built bad plans (a nonexistent scene, an unknown audience, clips that show a spoiler, a hand-edited EDL through `verify`) were checked for FAIL.
- **Tests that don't trust the verifier.** `test_every_timecode_exists_in_the_episode` and `test_no_protected_range_appears_in_any_trailer` re-derive source accuracy and spoiler safety directly from the input files.
- **Reading outputs, not just test results.** Several of the bugs below were found by reading generated plans and change reports while every test was passing.
- **Reproducibility.** Two runs on the same inputs must produce byte-identical trailers.

### Plausible but wrong: what the AI got wrong and how it was caught

| What looked fine | What was actually wrong | How it was caught | Fix |
|---|---|---|---|
| Prototype verifier "rejects unsafe scenes" | It silently passed scene ids that don't exist and audiences it didn't know, and ignored `allowed_tags`, contracts and durations | Probes with `scene_99` and audience `kids` returned PASS | Verifier rewritten; SRC-001 and AUD-001 tests |
| Prototype "Pydantic schemas" | Defined but never used; the sample outputs would not even pass them | Validating a sample output against `TrailerPlan` | Every plan is now validated before it is written |
| Prototype retry loop | Plans that still failed were saved as trailers; each round's feedback replaced the previous round's; scene ids parsed by string slicing | Code reading plus the brief's "do not force a trailer through validation" | Structured findings; `ready_for_editor: false`; unresolved issues listed |
| Rebuild: the no-model fallback plan passed validation | It contained the line "If they knew what I did with the papers...", which reveals the twist. Line-level spoilers came only from the model's story analysis, and without it the verifier did not know the line was protected | Reading the fallback plan's segments. **All tests were green at the time** | Recover the analysis from run memory when possible; otherwise an SPL-004 warning and a mandatory manual spoiler review; two regression tests |
| Rebuild: replacing a clip for a model-invented beat ("climax") | The replacement search reused the *rejected spoiler scene's own tags* as its target, steering toward twist-like material | Reading the young-adult repair history | Unknown beats now aim for the audience's overall tone |
| Rebuild: "music contract expired → 10 segments changed" | Technically true, but it hid the fact that one decision changed and no clip moved | Reading the change report | "Segments touched" and "clip changes" are reported separately |
| Rebuild: expired music swapped for "the best cleared track" | No cleared track matched the young-adult moods, so a melancholic track was chosen silently | Reading the revised plan's music reason | CRE-002 warning plus an editorial music-selection approval |
| Rebuild: kinship-term check | A naive word match would read "sent Dadi away" as addressing someone as grandmother | Design review of the lexicon approach | Only forms of address count (`vocative_kinship_terms`), with a test |
| Rebuild: a test asserting the no-model fallback costs ~$0 | The *test* was wrong: keyframe spot-checks still cost money | Test failure, then reading the cost breakdown | The test now asserts what was meant: no model calls |

### Testing with a real model (OpenAI gpt-5, `live_run/`)

The hand-written replay responses prove the verifier *can* catch mistakes. A live gpt-5 run was used to see which mistakes a real model actually makes. Its replies are recorded in `live_run/model_responses/` and replay exactly without a key (`run --replay-dir live_run/model_responses`).

**What gpt-5 got wrong, all caught and repaired by the verifier:**
- It used Munshi-ji's lines in all three trailers, although that actor's voice is not cleared for promos (RGT-003).
- It used the original mix of the cricket scene, which carries the uncleared "Pop Hit" (RGT-001), so the clip was switched to the dialogue stem.
- It gave text cards 2.0-2.5 s on screen when they needed up to 3.9 s to read (ACC-003).
- It proposed overlapping clips (TIM-003) and a family cut under the minimum length (TIM-001).
- In the first run it picked a hopeful music bed for the young adult trailer when a cleared tense track existed (CRE-002 warning).

**What it got right that the adversarial replays assumed it would get wrong:** no invented scenes, no twist clips, no stereotyping language, and no excluded insights. Real-model risk was concentrated in contracts, accessibility and timing, the "fine print" categories, which is where deterministic checks earn their place.

**What the real model exposed in *this* system:**

| Finding | Cause | Fix |
|---|---|---|
| The run crashed in repair | gpt-5 returned `alternate_text_cards` as plain strings; the code assumed `{text, seconds}` objects. The paid calls' replies were lost | Proposal shapes are normalised and logged; malformed segments dropped; live replies recorded to disk before parsing; regression test |
| 0 of 12 relationships verified, which silently weakened the subtitle-relationship check to warnings | The prompt never stated the direction convention or the allowed relation names, so gpt-5 wrote free text ("grandson to grandmother; affectionate bond") and cited actor ids | Prompt states direction and sends `relation_vocabulary`; actor-id cast refs resolve. Second run: 12 of 12 verified |
| The twist-hinting line was unprotected | gpt-5 listed only the confession scene's lines as reveals | Prompt asks for hint lines too; the second run protected it. Documented as a residual risk (KNOWN_LIMITATIONS 7) |
| Two set-up lines protected as spoilers | The model over-protects; the design accepts added protection | Kept by design; documented (KNOWN_LIMITATIONS 4) |

### Where AI was deliberately not trusted
- **Story analysis:** each claim is kept only if its evidence exists and supports it. In the sample run an invented relationship and an invented knife threat are dropped.
- **Spoilers:** the model can add protected facts but never remove editorial ones. In the sample run it missed the ending, and the editorial tag protected it anyway.
- **Creative proposals:** they never skip verification. Repairs are re-verified too.
- **Audience data:** bias-reviewed before use and checked again after.
