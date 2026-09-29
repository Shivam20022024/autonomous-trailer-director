# Architecture

## Pipeline

```
 supplied material ──► Package (validated, indexed)
        │
        ├─► Story analysis (model, untrusted) ──► evidence check ──► story_map.json
        │                                     └─► evidence check + editorial tags ──► spoiler_map.json
        ├─► policies + contracts ──► constraint_map.json          (rules linked to scenes/lines/shots/actors/music/markets)
        └─► audience profiles ──► bias review ──► usable insights
                                                     │
 for each audience:                                  ▼
   strategy brief ──► proposal (model, untrusted) ──► grounding ──► EDL v1
                                                                     │
                     ┌──────────── verifier (39 deterministic checks) ◄┘
                     │ errors?
                     ▼
                  repair: fix in place ─► trim ─► replace ─► drop      (up to 4 rounds, then stop)
                     │
                     ▼
   finalise: status, ready_for_editor, human approvals, cost, lower-cost fallback ──► *_trailer.json

 change event ──► patch inputs ──► changed entities ──► impact via depends_on ──► re-check all ──► repair failures only ──► v2 + change report
```

## Planning

1. **Understand the episode.** One model call returns characters, relationships, events, emotional turns, protected facts and sensitive content, each with evidence refs (`line:d04_1`, `moment:m07c`, `cast:bebe`). `story.py` keeps a claim only if every ref exists and the cited text supports it. For a relationship, the evidence must contain a keyword for that relation. For a protected fact, a reveal ref must contain one of the fact's keywords. In the sample run this drops an invented "Munshi-ji is Bebe's father" relationship and an invented knife threat.
2. **Build the constraint map.** `constraints.py` turns every contract clause and policy into a rule with an id, a source pointer, what it applies to and which check enforces it. It also derives a per-audience scene eligibility table (`blocked / restricted / caution / open`) that the planner uses to skip blocked scenes.
3. **Plan the audience promise first.** The brief sent to the model holds the audience goal, special care, rating rules, market, subtitle track, target duration, cleared music, blocked scenes and only the insights that passed bias review. The model must return objective, promise and emotional journey before its segments.
4. **Select and order moments.** The model proposes beats, clip refs, timecodes, audio, subtitle track, text cards and a music bed. **Grounding** (`planner.reground`) then fills in facts from the source: the exact dialogue text, the subtitle cues for the chosen track, the evidence list and `depends_on`, the list of every entity the segment relies on. Grounding never corrects or filters the model's choices. That is left to the verifier, so model mistakes stay visible.
5. **Verify** (below), **repair or reject** (below).

If no model is available, `deterministic_proposal` fills the audience's beat template with the best-scoring compliant clips. That is the degraded mode and the zero-cost fallback plan.

## Verification

`verifier.py` reads the EDL and the authoritative inputs only. It never sees prompts or model reasoning, and it does not read the constraint map, so a bug in the planning artefacts cannot weaken it. Each finding has a check id, severity, segment, message and a fix category.

| Area | Checks |
|---|---|
| Source accuracy | scene exists, timecodes inside the scene, ref inside the clip, verbatim dialogue, subtitle text equals the named track, evidence refs exist |
| Spoilers | clip overlaps a protected range; card/voice-over/subtitle states a protected fact; clip order implies one (e.g. cutting from "This is a forgery!" to Bebe looking down); coverage warning when only editorial tags are available |
| Ratings | forbidden scene tags; tags implied by *either* description (the AI saying "blood" counts even if the human didn't); forbidden shot tags; caution tags become warnings plus standards review; forbidden words in text |
| Rights | music cleared for promos, in the market, and unexpired through the campaign end; source music inside an original mix; on-screen actors cleared for video in the market; audible voices cleared; minors need legal sign-off |
| Story truth | text-card claims (death, ghosts, affairs...) must be supported by human descriptions or dialogue; a dialect subtitle may not change a story-map relationship; misleading-intensity ratio (young adult) |
| Dialect and culture | dialect audience gets its dialect track; stereotype lexicon; dialect not mainly in comic scenes; at least one cultural moment |
| Accessibility | dialogue is subtitled; reading speed ≤ 17 chars/s; text cards on screen long enough to read (12 chars/s); voice-over captioned |
| Other | biased insights not used, total and per-clip duration, no overlapping clips, music mood fit, budget |

**Spoiler definition.** A protected fact is a statement about the story, with the timecode ranges that reveal it, wording that states it, and cut orders that imply it. Editorial `spoiler / twist / ending` tags in the package are authoritative. The model can add protected facts only with verifiable reveal evidence, and can never remove one. In the sample run the model missed the ending, and the editorial tag protected it anyway.

## Repair and failure recovery

`repair.py` acts on each finding's fix category with the smallest change that could work:

| Order | Action | Example from the sample run |
|---|---|---|
| 1 | Fix in place | Uncleared "Pop Hit" in the original mix → switch to the dialogue stem plus a cleared bed; `dialect_b` "Bahu" → `dialect_a` "Beti"; stereotyping card → a compliant alternate; unreadable card → extended by 0.3 s; music not cleared in the region → swap the bed everywhere |
| 2 | Trim | A shot or line in the clip is the problem → cut it out if the remainder is long enough |
| 3 | Replace | Take the best candidate for the same beat that passes **every** segment check and the order checks with both neighbours |
| 4 | Drop | Nothing fits; the duration check then decides whether a segment must be added |

Every candidate change is re-checked before it is kept. Up to 4 rounds run. If a round makes no change, the loop stops and the plan is written as FAIL with its unresolved issues (`test_unrepairable_plan_is_rejected_not_forced_through`).

Other failure paths:

- **Model outage:** the model chain is tried in order (default `claude-opus-5-5`, then `claude-sonnet-5-5`; configurable, e.g. `gpt-5,gpt-5-mini`), then the deterministic planner is used.
- **Budget:** every call is checked against the call and cost limits *before* it is made; a skipped call falls through the same chain. The media spot-check is skipped if it would exceed its limit.
- **Invalid model output:** unparseable JSON is logged, and the next model is tried.
- **Lost story analysis:** if analysis fails and a previous run of the *same* episode (matching fingerprint) is on disk, its analysis is reused and re-verified. Otherwise every plan carries an SPL-004 warning and a required manual spoiler review, because line-level reveals outside tagged scenes can no longer be detected.

## Memory

- **Within a run:** the story map, spoiler map, constraint map and bias review are built once and shared by all three trailers. Each segment records `depends_on`: scene, lines, shots, subtitle cues, music, actors, policy, market and audience.
- **Across runs:** `run_state.json` stores input fingerprints and the verified story analysis. Change events reuse it, so there is no model call to re-analyse an unchanged story. A fresh run also uses it to recover from an analysis outage.
- **Decision log:** `decision_log.jsonl` numbers its entries instead of timestamping them, so identical inputs give byte-identical outputs (`test_runs_are_reproducible`).

## Multimodal processing

The system does not process video or audio frames. It grounds on the modalities the package supplies with timecodes: shot-level visual metadata (`moments` with characters and visual tags), dialogue lines, two dialect subtitle tracks, music cues and contracts, and two descriptions per scene (human and AI).

It cross-checks those sources:

- **Human vs AI description:** a sensitive term in only one description is a mismatch. It is treated conservatively for ratings and flagged for a human to check the footage (scene 5 "ghostly", scene 7 "blood").
- **Subtitles vs story map:** forms of address in each track are checked against the verified relationships (dialect B turns granddaughter into daughter-in-law).
- **Audio vs rights:** the diegetic music in each scene is checked whenever an original mix is used.
- **Evidence vs text:** every claim in the story map needs refs that exist and support it.

The per-trailer cost includes an *estimated* keyframe spot-check of the chosen clips, which is where a vision model would verify shots in production. It is costed but not executed; see KNOWN_LIMITATIONS.md.

## Responding to changes

`changes.py` maps a patch to entities (for example `music:music-02` or `cue:dialect_a:d08_1`). It intersects them with each segment's `depends_on` and with plan-level dependencies (bed track, rating policy, audience), and re-runs **all** checks on **all** trailers; that is cheap and catches dependency misses. It then repairs only what fails and writes a revision with a field-level diff, the repair reasons and new warnings or approvals.

| Event | Result in `sample_run/changes/` |
|---|---|
| Music rights expire (music-02) | Only the young-adult trailer depended on it. The bed is swapped, **0 clips change**, and a mood-mismatch warning asks an editor to pick the final track |
| Dialect subtitle now says "Bahu" | Only `dialect_region_s06` is impacted. The track switch fails (both dialect tracks now say "Bahu"), so that one clip is replaced |
| Scene description tells the AI to ignore a contract | Every trailer using scene 6 gets a security warning; the contract is still enforced and no clip changes |
| Clickbait card "Who will DIE for the inheritance?" | Rejected (TRU-001: no death in the episode); a compliant alternative is offered; the plan is unchanged |
| Preferred model goes down after planning | No plan depends on model availability; nothing is re-planned; future planning uses the next model in the chain |
| Actor loses a territory (in tests) | Only the dialect trailer's clips of that actor are replaced; the national trailers are re-checked and stay unchanged |

## Trust boundaries

- Model output (analysis and proposals) is untrusted. It is evidence-checked or verified before use.
- Scene descriptions, subtitles and notes are *data*. The system prompt says so, instruction-like text is flagged, and rules come only from `policies.json` and `contracts.json`, so injected text has nowhere to act.
- Audience data are hypotheses. Insights with exposure bias, a small sample, sensitive attributes or a spoiler-policy conflict are excluded before planning and rejected again by the verifier if a model cites them anyway.
- Historic engagement only breaks ties between compliant clips. The top-scoring scene (the twist, 0.95) is rejected and logged as `high_performing_idea_rejected`.

## What would fail first at scale

1. **Lexicon checks** (claims, stereotypes, kinship, injection): they are exact and explainable, but paraphrase evades them and they need a lexicon per language and dialect. The next step is to keep them as hard gates and add model-based classifiers that can only *add* flags.
2. **Story analysis quality on long or real footage:** line-level spoiler protection depends on it. Mitigations: chunked analysis, two independent analyses with disagreements escalated to a human, and editorial tagging at ingest.
3. **Replacement search** is a linear scan over every clip per slot. That is fine for a 14-minute episode but needs an index for a season.
4. **Contract data freshness:** the system is only as right as `contracts.json`. That is why legal sign-off stays human.
