# Known limitations and decisions that stay with humans

## Limitations

### Inputs and modes
1. **The sample data is self-authored.** No official episode package was supplied, so `data/` holds a fictional 14.5-minute episode (11 scenes, 22 lines, 24 shots, two dialect tracks) plus contracts, policies, profiles, historic scores and a cost sheet. It was written to exercise every constraint in the brief. The system reads everything from `data/`, so a real package can replace it if it follows the same schema (`models.py`).
2. **The default replay responses are hand-written.** `data/replay/*.json` are adversarial: they deliberately contain an invented scene, the top-scoring spoiler, an uncleared voice, a stereotyping card, a relationship-changing subtitle and a biased insight, to show that the verifier catches each one. Real-model output is in `live_run/` (item 3).
3. **Live mode has been run with OpenAI gpt-5, not with Claude.** `live_run/` is a real gpt-5 run, and its recorded replies (`live_run/model_responses/`) replay exactly without a key. The Claude adapter has only been exercised against a local fake API server (request shape and parsing), because no Anthropic key was available. One live run is a single sample: model output varies between runs.
4. **Over-protection by the model is accepted.** A model may add protected facts, and each needs only one reveal ref that contains its keywords. In the gpt-5 run this protected two set-up lines ("You knew he left it to the trust", the will reading) as spoilers, costing the young adult trailer two strong conflict clips. That is the safe direction by design; an editor can release a line.
5. **No pixel- or audio-level analysis.** The system relies on the supplied shot metadata and the two descriptions per scene. The "keyframe spot-check" in the cost is an estimate of what a vision pass would cost; it is not executed. On-screen presence (which matters for actor rights) is inferred from shot and line metadata. With no metadata, the whole scene cast is assumed, which is conservative.

### Checks
6. **Lexicon-based checks are exact but narrow.** Unsupported claims, stereotypes, forms of address and injected instructions are matched against word lists in `policies.json`. Paraphrase gets through ("Someone won't survive this inheritance" is not caught), and the lists need a native speaker per dialect. Forms of address are only checked when used vocatively ("Beti, ..." / "..., Dadi.").
7. **Line-level spoiler detection depends on story analysis.** Editorial tags protect whole scenes. A single revealing line elsewhere is only known from the (evidence-checked) model analysis. Without it, plans carry SPL-004 and a mandatory manual spoiler review. This is real, not theoretical: in the first gpt-5 run the model did not list "If they knew what I did with the papers..." as a reveal, so it was unprotected (no trailer happened to use it). After the prompt asked for hint lines too, the model listed it. That improves the odds but guarantees nothing, which is why editorial line-level tagging stays on the list of recommended human steps.
8. **The misleading-intensity check is a ratio of tagged durations,** not a judgement of how the cut feels.
9. **The dialect-as-comic-device check is coarse.** It counts subtitled lines from humour-tagged scenes. Dadi's sincere proverb sits in a scene tagged `humour`, so it counts against the limit.

### Creative quality
10. **Replacements are chosen by tag score,** not by narrative sense. A repaired beat can be compliant but weaker, and its beat label can overstate it: the family "tease" slot ends up with a homecoming shot because every mystery shot is blocked for family viewers. The editor pass exists for this.
11. **When no cleared music fits the mood,** the closest cleared track is used and flagged (CRE-002). The system does not look for new music.

### Operations
12. **Change events are applied to the base run one at a time,** not stacked. Stacking several events needs a run-to-run chain, which is not built.
13. **Costs are estimates.** Token counts in mock mode are characters ÷ 4. Live mode uses the API's reported usage.
14. **No concurrency or locking** on the run directory, and no authentication. This is a single-user CLI.

## Decisions that must remain with humans

The system lists these in each plan's `human_approvals_required`, with owner and segments.

| Decision | Owner | Why not automated |
|---|---|---|
| Final pacing, music edit and emotional read of each cut | Editorial | Rhythm, performance and whether the cut feels right can't be checked by rules |
| Final music choice when no cleared track fits the intended mood | Editorial | Taste and brand fit |
| Checking footage where human and AI descriptions disagree (scene 5 "ghost", scene 7 "blood") | Editorial | Needs someone to watch the frames |
| Manual spoiler review when story analysis is unavailable | Editorial | Line-level reveals can't be detected without it |
| Caution-tagged content for each rating (conflict or tension for families, intensity for young adults) | Standards | Degree and context matter |
| Every promo use of a minor | Legal | Guardian consent and child-performer rules |
| Confirming the contract data behind any rights-driven repair | Legal | The system is only as current as `contracts.json` |
| Dialect subtitles, forms of address and cultural framing of the dialect trailer | Cultural reviewer from the region | Lexicons can't judge authenticity or tone |
| Source metadata that contained instructions (possible tampering) | Security / metadata owner | Where it came from needs investigating |
| Appeals against a rejected marketing request | Editorial with marketing | The verifier blocks it; changing the underlying policy is a human call |
