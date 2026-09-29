"""Changes after planning: identify affected decisions, revise only those, re-check, record why."""
import json
from pathlib import Path

from trailer_director.changes import apply_change

EVENTS = Path(__file__).resolve().parents[1] / "events"


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def by_aud(report):
    return {t["audience_id"]: t for t in report["trailers"]}


def test_changed_contract_revises_only_the_affected_decision(base_run, tmp_path):
    run_dir, res = base_run
    report = apply_change(run_dir, EVENTS / "music_rights_expire.json", out_dir=tmp_path)
    rows = by_aud(report)
    assert "music:music-02" in report["changed_entities"]
    assert rows["young_adult"]["impacted"] and rows["young_adult"]["clip_changes"] == 0
    assert not rows["family"]["impacted"] and not rows["dialect_region"]["impacted"]
    assert not list(tmp_path.glob("family_trailer_v*.json")) and not list(tmp_path.glob("dialect_region_trailer_v*.json"))

    before, after = res["plans"]["young_adult"], load(tmp_path / "young_adult_trailer_v2.json")
    assert before["music_plan"]["bed_track"] == "music-02"
    assert after["music_plan"]["bed_track"] not in ("music-02", "music-03")
    assert [(s["video"], s["source_in"], s["source_out"]) for s in before["segments"]] == \
           [(s["video"], s["source_in"], s["source_out"]) for s in after["segments"]]
    assert after["validation"]["status"] != "FAIL"
    rev = after["revisions"][-1]
    assert rev["event_id"] == "music_rights_expire" and rev["repair_actions"][0]["action"] == "swap_music"
    # No cleared track fits the young-adult moods any more: that must surface for an editor, not pass silently.
    assert any(w["check_id"] == "CRE-002" for w in after["validation"]["warnings"])
    assert any(a["approval"] == "editorial: music selection" for a in after["human_approvals_required"])


def test_actor_contract_change_hits_one_market_only(base_run, tmp_path):
    run_dir, _ = base_run
    event = {"event_id": "amar_region_revoked", "type": "contract_update",
             "description": "Amar's actor loses clearance in region_east.",
             "patch": [{"file": "contracts", "path": ["actors", {"actor_id": "act-01"}, "territories"], "value": ["national"]}]}
    (tmp_path / "e.json").write_text(json.dumps(event))
    report = apply_change(run_dir, tmp_path / "e.json", out_dir=tmp_path / "out")
    rows = by_aud(report)
    assert rows["dialect_region"]["impacted"] and rows["dialect_region"]["clip_changes"] > 0
    assert rows["family"]["impacted"] and rows["family"]["clip_changes"] == 0  # depends on act-01, but national is still cleared
    after = load(next((tmp_path / "out").glob("dialect_region_trailer_v*.json")))
    assert after["validation"]["status"] != "FAIL"
    assert all("actor:act-01" not in s["depends_on"] for s in after["segments"])


def test_dialect_subtitle_change_is_caught_and_repaired(base_run, tmp_path):
    run_dir, _ = base_run
    report = apply_change(run_dir, EVENTS / "dialect_subtitle_change.json", out_dir=tmp_path)
    rows = by_aud(report)
    assert rows["dialect_region"]["impacted_segments"] == ["dialect_region_s06"]
    assert not rows["family"]["impacted"] and not rows["young_adult"]["impacted"]
    after = load(tmp_path / "dialect_region_trailer_v2.json")
    assert not any("Bahu" in ((s.get("subtitle") or {}).get("text") or "") for s in after["segments"])
    assert after["validation"]["status"] != "FAIL"


def test_injected_instruction_in_metadata_is_ignored(base_run, tmp_path):
    run_dir, _ = base_run
    report = apply_change(run_dir, EVENTS / "description_injection.json", out_dir=tmp_path)
    for row in report["trailers"]:
        assert row["clip_changes"] == 0
        assert any(w.startswith("SEC-001") for w in row["new_warnings"])
    for f in tmp_path.glob("*_trailer_v2.json"):
        plan = load(f)
        assert not any(s["video"] == "scene_06" and s["audio"] == "original_mix" for s in plan["segments"])
        assert any(a["owner"] == "security" for a in plan["human_approvals_required"])


def test_clickbait_marketing_request_is_rejected_with_alternatives(base_run, tmp_path):
    run_dir, _ = base_run
    report = apply_change(run_dir, EVENTS / "marketing_clickbait.json", out_dir=tmp_path)
    assert report["outcome"].startswith("Request rejected")
    assert {v["check_id"] for v in report["rejection"]["violations"]} == {"TRU-001"}
    assert report["rejection"]["compliant_alternatives"]
    assert not list(tmp_path.glob("*_trailer_v*.json"))


def test_model_outage_after_planning_needs_no_replanning(base_run, tmp_path):
    run_dir, _ = base_run
    report = apply_change(run_dir, EVENTS / "model_outage.json", out_dir=tmp_path)
    assert not any(t["impacted"] for t in report["trailers"])
    assert report["model_fallback"]["next_planning_source"] == "claude-sonnet-5-5"
