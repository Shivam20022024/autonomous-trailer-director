# Autonomous Trailer Director

Plans three audience-specific trailer edit decision lists (EDLs) from one episode, proves each one against story truth, ratings, rights, accessibility and cultural rules, repairs what fails, and re-plans selectively when a contract, policy, subtitle or audience fact changes.

The creative step is done by a language model and is treated as untrusted. A deterministic verifier with 39 checks decides what ships. Nothing is forced through validation: a plan that cannot be repaired is written with `status: FAIL`, `ready_for_editor: false`, and a list of unresolved issues.

## View the dashboard

- **Online, no setup (GitHub Pages):**
  - Adversarial replay run: <https://Shivam20022024.github.io/autonomous-trailer-director/sample_run/dashboard.html>
  - Real gpt-5 run: <https://Shivam20022024.github.io/autonomous-trailer-director/live_run/dashboard.html>
- **Locally, after cloning:** `python run_director.py dashboard`, or double-click `sample_run/dashboard.html`. It is a single offline file: no server or internet needed.

## Quick start

Needs Python 3.10+. No API key is needed: the default mode replays recorded model responses.

```bash
git clone https://github.com/Shivam20022024/autonomous-trailer-director.git
cd autonomous-trailer-director
pip install -r requirements.txt

python run_director.py run                                                # plan all three trailers -> sample_run/
python run_director.py dashboard                                          # open sample_run/dashboard.html
python run_director.py change --event events/music_rights_expire.json    # apply a change to that run
python run_director.py verify sample_run/family_trailer.json              # check any trailer plan
python -m pytest                                                          # 55 tests
```

On Windows PowerShell, the same commands work with `\` or `/` in paths.

## Command reference

All commands are run from the project folder as `python run_director.py <command> [options]`. Alternatively, run `pip install -e .` once and use `trailer-director <command> [options]`.

### Global option

| Option | Effect |
|---|---|
| `--quiet` | Print only the final summary, not each decision as it happens. Goes **before** the command: `python run_director.py --quiet run` |
| `-h`, `--help` | Help for the tool or any command: `python run_director.py run --help` |

### `run`: plan, verify and repair the trailers

```bash
python run_director.py run [options]
```

| Option | Default | Effect |
|---|---|---|
| `--data DIR` | `data` | Folder with the supplied material |
| `--episode FILE` | `<data>/episode_package.json` | Use a different episode package |
| `--audience-defs FILE` | `<data>/audiences.json` | Use different audience definitions |
| `--audiences IDS` | all three | Comma-separated audience ids, e.g. `family,young_adult` |
| `--out DIR` | `sample_run` | Where to write the plans, maps, logs, report and dashboard |
| `--mode mock\|live` | `mock` | `mock` replays recorded model responses; `live` calls real models |
| `--replay-dir DIR` | `<data>/replay` | Mock mode: which recorded responses to replay |
| `--model-chain MODELS` | `claude-opus-5-5,claude-sonnet-5-5` | Models to try in order. `claude-*` models use `ANTHROPIC_API_KEY`; others (e.g. `gpt-5`) use `OPENAI_API_KEY` |
| `--unavailable-model MODEL` | none | Simulate an outage of a model; repeatable. Falls back down the chain, then to the no-model planner |

Examples:

```bash
# Default: all three trailers from the hand-written adversarial replays
python run_director.py run

# Only two audiences, written somewhere else
python run_director.py run --audiences family,young_adult --out my_run

# Your own episode package and audience definitions
python run_director.py run --episode path/to/episode_package.json --audience-defs path/to/audiences.json --out my_run

# Replay the recorded real gpt-5 run: no key, no cost, same decisions
python run_director.py run --replay-dir live_run/model_responses --out replay_of_live

# Simulate the preferred model going down (falls back to the next model)
python run_director.py run --unavailable-model claude-opus-5-5 --out outage_run

# Simulate every model going down (deterministic planner, no model calls)
python run_director.py run --unavailable-model claude-opus-5-5 --unavailable-model claude-sonnet-5-5 --out no_model_run
```

**Live mode (real model calls, costs money).** Replies are recorded to `<out>/model_responses/`, so a live run can be replayed later for free with `--replay-dir`. The budget limits in `data/config.json` are checked before each call.

PowerShell:

```powershell
pip install openai                      # or: pip install anthropic   (for claude-* models)
$env:OPENAI_API_KEY = "sk-..."          # or: $env:ANTHROPIC_API_KEY = "sk-ant-..."
python run_director.py run --mode live --model-chain gpt-5,gpt-5-mini --out live_run
```

bash:

```bash
pip install openai                      # or: pip install anthropic
export OPENAI_API_KEY="sk-..."          # or: export ANTHROPIC_API_KEY="sk-ant-..."
python run_director.py run --mode live --model-chain gpt-5,gpt-5-mini --out live_run
```

Never put a key in a file inside this project.

### `change`: apply a change event to an earlier run

```bash
python run_director.py change --event FILE [--run DIR] [--data DIR] [--out DIR]
```

| Option | Default | Effect |
|---|---|---|
| `--event FILE` | required | The change event JSON |
| `--run DIR` | `sample_run` | The run to revise (run `run` first) |
| `--data DIR` | the data folder recorded in the run | Supplied material to patch |
| `--out DIR` | `<run>/changes/<event_id>` | Where to write the change report and revised trailers |

Included events (each is applied to the base run on its own, not stacked):

```bash
python run_director.py change --event events/music_rights_expire.json      # music-02 rights end before the campaign does
python run_director.py change --event events/dialect_subtitle_change.json  # a dialect subtitle turns granddaughter into daughter-in-law
python run_director.py change --event events/description_injection.json    # a scene description tells the AI to ignore a contract
python run_director.py change --event events/marketing_clickbait.json      # marketing asks for "Who will DIE for the inheritance?"
python run_director.py change --event events/model_outage.json             # the preferred model goes down after planning
```

To revise the real-model run instead: `python run_director.py change --run live_run --event events/music_rights_expire.json`.

### `verify`: check any trailer plan

```bash
python run_director.py verify PLAN_FILE [--data DIR]
```

Runs all 39 checks on a trailer JSON (for example one you edited by hand) and lists every error and warning.

```bash
python run_director.py verify sample_run/family_trailer.json
python run_director.py verify sample_run/changes/music_rights_expire/young_adult_trailer_v2.json
```

### `dashboard`: build and open the dashboard

```bash
python run_director.py dashboard [--run DIR] [--no-open]
```

| Option | Default | Effect |
|---|---|---|
| `--run DIR` | `sample_run` | Which run's dashboard to build |
| `--no-open` | off | Only write `<run>/dashboard.html`; don't open the browser |

`run` and `change` update the dashboard automatically; this command is for opening it (or rebuilding it after editing a file by hand).

```bash
python run_director.py dashboard                    # adversarial replay run
python run_director.py dashboard --run live_run     # real gpt-5 run
```

### Tests

```bash
python -m pytest                           # all 55 tests
python -m pytest tests/test_verifier.py    # only the checker
python -m pytest -k spoiler                # tests with "spoiler" in the name
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success: every trailer is ready for an editor (`run`), or the plan passed (`verify`) |
| `1` | Input error, e.g. missing file, unknown audience or invalid episode package |
| `2` | Finished, but at least one trailer (`run`) or the checked plan (`verify`) has status `FAIL` |

## Seeing what it does

- **Console:** `run` and `change` print each decision as it happens: model calls, rejected model claims, the checker's verdicts, and every repair with its reason.
- **Dashboard (`dashboard.html` in each run folder):**
  - **Overview:** trailer cards, where every clip comes from in the episode with the protected spoiler zones, budget, and what the safety layer stopped.
  - **One tab per trailer:** structure, the edit decision list with evidence, repairs before and after, warnings, human approvals and cost.
  - **Story & spoilers:** protected facts, verified relationships, rejected model claims, the insight review and scene eligibility.
  - **Changes** and a searchable **Decision log**.

  Link to a tab with `#<tab>`, e.g. `dashboard.html#dialect_region`.

## What a run produces (`sample_run/`)

| File | Contents |
|---|---|
| `dashboard.html` | Visual summary of everything below |
| `family_trailer.json`, `young_adult_trailer.json`, `dialect_region_trailer.json` | EDL for each trailer: promise, emotional journey, music plan, segments with exact source timecodes, dialogue, subtitles, text cards, reasons, evidence, dependencies, validation, repair history, human approvals, cost and a lower-cost fallback |
| `story_map.json` | Characters, relationships, events and emotional turns. Only verified claims are kept; rejected model claims are listed. Also contains description mismatches and flags for instruction-like text |
| `spoiler_map.json` | Protected facts with protected timecode ranges, forbidden wording and forbidden cut orders |
| `constraint_map.json` | Policies and contracts turned into rules linked to scenes, lines, shots, actors, music and markets, plus a per-audience scene eligibility table |
| `audience_insight_review.json` | Bias review of the audience data, and which insights are excluded and why |
| `decision_log.jsonl` | Structured log of every decision, model call, rejection and repair |
| `validation_report.md` | Human-readable summary of all of the above |
| `run_summary.json`, `run_state.json` | Statuses, budget, trailer distinctness, and the run's memory (input fingerprints plus the cached story analysis) |
| `changes/<event>/` | Change report, revised trailers (`*_v2.json`), the updated constraint map, and the decision log for each change event |

`live_run/` has the same layout for a real OpenAI gpt-5 run (about $0.28 of model calls), plus `model_responses/` with the raw replies. `sample_run/` uses the hand-written adversarial replays in `data/replay/`, which deliberately contain the mistakes the brief's surprise events describe.

## Repository layout

```
data/                  supplied material (sample, see KNOWN_LIMITATIONS.md), config, replay/ recorded model responses
events/                change events for the surprise scenarios
src/trailer_director/
  cli.py               command-line interface
  package.py           loads and validates the inputs; lookups (refs, on-screen cast, music rights)
  story.py             story map + spoiler map; evidence-checks every model claim
  constraints.py       constraint map
  bias.py              audience-insight review
  llm.py               model fallback chain (replay | Claude | OpenAI) with budget checks and response recording
  planner.py           audience strategy, proposal, grounding into an EDL, candidate search
  verifier.py          the 39 deterministic checks
  repair.py            smallest-change repair, then replace, then drop; never bypasses the verifier
  changes.py           change events: impact analysis, selective revision, change reports
  orchestrator.py      end-to-end run, finalisation, outputs
  report.py            validation_report.md
  dashboard.py         dashboard.html
  console.py           live console output
tests/                 checker, pipeline, change-handling, model-output and dashboard tests
sample_run/            output of the default run (adversarial replays)
live_run/              output of a real gpt-5 run, with its recorded replies
run_director.py        entry point (no install needed)
```

## Where each requirement in the brief is met

| Brief | Where |
|---|---|
| CLI that takes the episode package and audience definitions | `python run_director.py run --episode ... --audience-defs ...` |
| Three plans with exact timecodes and validation | `sample_run/*_trailer.json` (and `live_run/`) |
| Story map, spoiler map, constraint map, decision log | `sample_run/` |
| Tests: missing scene, rights restriction, spoiler, policy failure, changed contract | `tests/test_verifier.py` (`test_missing_scene_is_rejected`, `test_uncleared_*`, `test_actor_*`, `test_spoiler_*`, `test_family_policy_*`), `tests/test_changes.py` (`test_changed_contract_*`, `test_actor_contract_change_*`) |
| Mock or replay mode | the default `mode: mock` (`data/replay/`, or `--replay-dir live_run/model_responses`) |
| Surprise events | `events/` and `tests/test_changes.py`; the model-hallucination and top-scoring-spoiler cases happen in the base run (see the dashboard or report) |
| Architecture, AI collaboration and limitations notes | `ARCHITECTURE.md`, `AI_COLLABORATION.md`, `KNOWN_LIMITATIONS.md` |
