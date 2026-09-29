"""End-to-end properties of a full run."""
import json

from conftest import edit_json

from trailer_director.models import TrailerPlan
from trailer_director.orchestrator import run
from trailer_director.package import Package
from trailer_director.timecode import overlaps, parse_tc

AUDIENCES = ("family", "young_adult", "dialect_region")


def test_run_writes_every_required_artefact(base_run):
    out, _ = base_run
    for name in ["story_map.json", "spoiler_map.json", "constraint_map.json", "decision_log.jsonl", "validation_report.md",
                 "family_trailer.json", "young_adult_trailer.json", "dialect_region_trailer.json", "run_state.json"]:
        assert (out / name).exists(), name


def test_all_trailers_pass_and_match_schema(base_run):
    _, res = base_run
    for aud in AUDIENCES:
        plan = res["plans"][aud]
        TrailerPlan.model_validate(plan)
        assert plan["validation"]["status"] in ("PASS", "PASS_WITH_WARNINGS")
        assert plan["ready_for_editor"]
        lo, hi = plan["target_duration_seconds"]
        assert lo <= plan["duration_seconds"] <= hi


def test_every_timecode_exists_in_the_episode(base_run, data_dir):
    """Independent re-check of source accuracy, not using the verifier."""
    _, res = base_run
    pkg = Package.load(data_dir)
    for plan in res["plans"].values():
        for s in plan["segments"]:
            scene = pkg.scene(s["video"])
            assert scene is not None
            assert scene.start_s <= parse_tc(s["source_in"]) < parse_tc(s["source_out"]) <= scene.end_s


def test_no_protected_range_appears_in_any_trailer(base_run):
    out, res = base_run
    spoilers = json.loads((out / "spoiler_map.json").read_text(encoding="utf-8"))
    ranges = [(r["scene_id"], parse_tc(r["start"]), parse_tc(r["end"])) for f in spoilers["protected_facts"]
              for r in f["protected_ranges"]]
    for plan in res["plans"].values():
        for s in plan["segments"]:
            a, b = parse_tc(s["source_in"]), parse_tc(s["source_out"])
            assert not any(sc == s["video"] and overlaps(a, b, r0, r1) for sc, r0, r1 in ranges)


def test_trailers_are_genuinely_different(base_run):
    out, _ = base_run
    summary = json.loads((out / "run_summary.json").read_text(encoding="utf-8"))
    assert not any(row["too_similar"] for row in summary["distinctness"])


def test_model_mistakes_are_caught_and_logged(base_run):
    out, res = base_run
    log = [json.loads(line) for line in (out / "decision_log.jsonl").read_text(encoding="utf-8").splitlines()]
    kinds = {e["kind"] for e in log}
    assert {"hallucination_rejected", "high_performing_idea_rejected", "claim_rejected", "injection_flag",
            "insight_excluded", "spoiler_backfill"} <= kinds
    ya = res["plans"]["young_adult"]
    assert "scene_10" not in {s["video"] for s in ya["segments"]}
    assert "scene_14" not in {s["video"] for s in ya["segments"]}
    assert "ya-1" not in ya["insights_used"]


def test_repairs_are_minimal_where_possible(base_run):
    """Rights problems in the original mix are fixed by switching to the dialogue stem, not by dropping the clip."""
    _, res = base_run
    fam = res["plans"]["family"]
    actions = {(a["action"], a["segment_id"]) for a in fam["repair_history"]}
    assert ("use_dialogue_stem", "family_s10") in actions
    s10 = next(s for s in fam["segments"] if s["segment_id"] == "family_s10")
    assert s10["source_ref"] == "moment:m06b" and s10["audio"] == "dialogue_and_music"


def test_every_plan_names_human_approvals_and_cost(base_run):
    _, res = base_run
    for plan in res["plans"].values():
        owners = {a["owner"] for a in plan["human_approvals_required"]}
        assert "editorial" in owners
        assert plan["cost"]["estimated_usd"] > 0
        assert any(f["estimated_usd"] == 0.0 for f in plan["cost"]["lower_cost_fallback"])
    assert "cultural" in {a["owner"] for a in res["plans"]["dialect_region"]["human_approvals_required"]}


def test_runs_are_reproducible(base_run, tmp_path, data_dir):
    out, _ = base_run
    run(data_dir, tmp_path)
    for aud in AUDIENCES:
        assert (tmp_path / f"{aud}_trailer.json").read_text() == (out / f"{aud}_trailer.json").read_text()


def test_recorded_real_model_run_replays_and_passes(tmp_path, data_dir):
    """live_run/model_responses holds real gpt-5 replies; they must replay without a key and still verify."""
    recorded = data_dir.parent / "live_run" / "model_responses"
    res = run(data_dir, tmp_path, replay_dir=recorded)
    assert len(res["context"].story_map["relationships"]) >= 10
    for plan in res["plans"].values():
        assert plan["ready_for_editor"], plan.get("unresolved_issues")


def test_preferred_model_unavailable_falls_back_down_the_chain(tmp_path, data_dir):
    res = run(data_dir, tmp_path, ["family"], unavailable=["claude-opus-5-5"])
    plan = res["plans"]["family"]
    assert plan["planning_source"]["model"] == "claude-sonnet-5-5"
    assert plan["ready_for_editor"]


def test_all_models_unavailable_uses_deterministic_planner(tmp_path, data_dir):
    res = run(data_dir, tmp_path, list(AUDIENCES), unavailable=["claude-opus-5-5", "claude-sonnet-5-5"])
    for plan in res["plans"].values():
        assert plan["planning_source"]["proposal"] == "deterministic"
        assert plan["validation"]["status"] != "FAIL", plan.get("unresolved_issues")
        assert plan["cost"]["breakdown"]["model_calls"] == []
        # Without a verified story analysis, line-level spoilers can't be detected: say so, don't pass silently.
        assert any(w["check_id"] == "SPL-004" for w in plan["validation"]["warnings"])
        assert any("manual spoiler review" in a["approval"] for a in plan["human_approvals_required"])


def test_outage_recovers_story_analysis_from_run_memory(tmp_path, data_dir):
    """A previous run of the same episode leaves a verified analysis; an outage must not lose line-level spoilers."""
    run(data_dir, tmp_path)
    res = run(data_dir, tmp_path, unavailable=["claude-opus-5-5", "claude-sonnet-5-5"])
    assert res["context"].spoiler_map["coverage"] == "story_analysis+editorial"
    for plan in res["plans"].values():
        assert plan["planning_source"]["proposal"] == "deterministic"
        assert not any(d["line_id"] == "d08_3" for s in plan["segments"] for d in s["dialogue"])
        assert not any(w["check_id"] == "SPL-004" for w in plan["validation"]["warnings"])


def test_budget_limit_is_enforced(data_copy, tmp_path):
    edit_json(data_copy / "config.json", lambda c: c["budget"].update(max_model_calls=1))
    res = run(data_copy, tmp_path, ["family"])
    ctx = res["context"]
    assert ctx.budget.calls <= 1
    assert ctx.log.of_kind("budget_skip")
    assert res["plans"]["family"]["planning_source"]["proposal"] == "deterministic"


def test_unrepairable_plan_is_rejected_not_forced_through(data_copy, tmp_path):
    everything = ["warmth", "humour", "family", "atmospheric", "quiet", "dialogue-heavy", "emotional", "mystery",
                  "conflict", "tense", "identity", "dialect-rich", "intense", "frightening"]
    edit_json(data_copy / "policies.json",
              lambda p: p["rating_policies"]["family"].update(forbidden_tags=everything))
    res = run(data_copy, tmp_path, ["family"])
    plan = res["plans"]["family"]
    assert plan["validation"]["status"] == "FAIL"
    assert plan["ready_for_editor"] is False
    assert plan["unresolved_issues"]
