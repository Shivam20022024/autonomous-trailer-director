"""End-to-end run: understand -> constrain -> plan -> verify -> repair/reject -> report."""
import hashlib
import json
from pathlib import Path

from .bias import review_insights
from .budget import Budget
from .constraints import build_constraint_map
from .dashboard import build_dashboard
from .llm import ModelRouter
from .logbook import DecisionLog
from .models import TrailerPlan
from .package import Package, PackageError
from .planner import Planner
from .repair import Repairer
from .report import write_validation_report
from .story import analyze_episode, build_spoiler_map, build_story_map
from .verifier import Verifier

OWNERS = {"legal": "legal", "cultural": "cultural", "standards": "standards", "security": "security",
          "accessibility": "accessibility", "editorial": "editorial"}

ASSUMPTIONS = [
    "On-screen presence is inferred from shot and dialogue metadata; with no metadata the whole scene cast is assumed present.",
    "Scene tags and human descriptions are authoritative; AI descriptions only ever add caution, never remove it.",
    "Rights expiry is checked against the configured campaign window, not just the plan date.",
    "Historic engagement scores are hypotheses from earlier campaigns and only break ties between compliant clips.",
    "Dialogue and music stems are available, so 'dialogue_and_music' replaces any source music in the original mix.",
]


class Context:
    """Everything derived from one version of the inputs."""

    def __init__(self, pkg, log, budget, router, analysis, analysis_meta):
        self.pkg, self.log, self.budget, self.router = pkg, log, budget, router
        self.analysis = analysis
        self.story_map = build_story_map(pkg, analysis, analysis_meta, log)
        self.spoiler_map = build_spoiler_map(pkg, analysis, log)
        self.bias_review = review_insights(pkg)
        self.constraint_map = build_constraint_map(pkg, self.spoiler_map, self.bias_review)
        self.verifier = Verifier(pkg, self.story_map, self.spoiler_map)
        self.planner = Planner(pkg, self.story_map, self.spoiler_map, self.constraint_map, self.bias_review,
                               self.verifier, router, log)
        self.repairer = Repairer(pkg, self.planner, self.verifier, log)


def make_context(pkg, mode=None, unavailable=(), log=None, cached_analysis=None, recovery_analysis=None,
                 model_chain=None, replay_dir=None, record_dir=None):
    cfg = pkg.config
    log = log or DecisionLog(cfg["run_id"])
    budget = Budget(cfg["budget"], pkg.cost_sheet)
    replay_dir = Path(replay_dir) if replay_dir else (pkg.data_dir or Path("data")) / "replay"
    router = ModelRouter(mode or cfg["mode"], model_chain or cfg["model_chain"], set(cfg.get("unavailable_models", [])) | set(unavailable),
                         replay_dir, budget, log, record_dir)
    log.record("ingest", f"Loaded {pkg.episode.episode_id} '{pkg.episode.title}': {len(pkg.scenes)} scenes, "
               f"{len(pkg.lines)} lines, {len(pkg.moments)} shots, {len(pkg.subtitles['tracks'])} subtitle tracks")
    analysis, meta = analyze_episode(pkg, router, log, cached=cached_analysis, recovery=recovery_analysis)
    return Context(pkg, log, budget, router, analysis, meta)


def verify_and_repair(ctx, plan, aud) -> dict:
    max_rounds = ctx.pkg.config["max_repair_rounds"]
    result = ctx.verifier.verify_plan(plan)
    ctx.log.record("verification", f"Initial check: {result['status']} ({len(result['errors'])} errors, "
                   f"{len(result['warnings'])} warnings)", aud["audience_id"],
                   errors=[f"{e['check_id']}@{e['segment_id']}" for e in result["errors"]])
    for rnd in range(1, max_rounds + 1):
        if not result["errors"]:
            break
        actions = ctx.repairer.repair(plan, aud, result, rnd)
        plan["repair_history"].extend(actions)
        result = ctx.verifier.verify_plan(plan)
        ctx.log.record("verification", f"After repair round {rnd}: {result['status']} ({len(result['errors'])} errors, "
                       f"{len(result['warnings'])} warnings)", aud["audience_id"],
                       errors=[f"{e['check_id']}@{e['segment_id']}" for e in result["errors"]])
        if not actions:
            ctx.log.record("repair_stalled", "No further repair possible; remaining errors are reported, not forced through",
                           aud["audience_id"])
            break
    return result


def finalize(ctx, plan, aud, result, shared_usd=0.0, spot_check_seconds=None, keep_cost=False) -> dict:
    """Attach validation, approvals and cost. Revisions spot-check only the clips they changed."""
    plan["duration_seconds"] = round(sum(s.get("duration_seconds") or 0 for s in plan["segments"]), 3)
    minutes = (plan["duration_seconds"] if spot_check_seconds is None else spot_check_seconds) / 60
    ok, why = ctx.budget.can_analyse_media(minutes)
    if ok and minutes > 0:
        ctx.budget.charge_media("keyframe spot-check of selected clips", minutes, aud["audience_id"])
    elif not ok:
        ctx.log.record("budget_skip", f"Keyframe spot-check skipped: {why}", aud["audience_id"])
    plan["validation"] = result
    plan["ready_for_editor"] = result["status"] != "FAIL"
    plan["human_approvals_required"] = _approvals(plan, aud, result)
    plan["assumptions"] = list(ASSUMPTIONS)
    if not keep_cost:
        plan["cost"] = _cost(ctx, plan, aud, shared_usd, spot_checked=ok)
    plan.pop("unresolved_issues", None)
    if not plan["ready_for_editor"]:
        plan["unresolved_issues"] = [f"{e['check_id']} ({e['segment_id']}): {e['message']}" for e in result["errors"]]
    TrailerPlan.model_validate(plan)
    ctx.log.record("finalize", f"{plan['trailer_id']}: {result['status']}, {plan['duration_seconds']}s, "
                   f"{len(plan['segments'])} segments, ready_for_editor={plan['ready_for_editor']}", aud["audience_id"])
    return plan


def _approvals(plan, aud, result):
    out = {}
    for w in result["warnings"] + result["errors"]:
        key = w.get("approval") or ("editorial: resolve blocking error" if w["severity"] == "error" else None)
        if not key:
            continue
        item = out.setdefault(key, {"approval": key, "owner": OWNERS.get(key.split(":")[0].split("/")[0], "editorial"),
                                    "reasons": [], "segments": []})
        if w["message"] not in item["reasons"]:
            item["reasons"].append(w["message"])
        if w["segment_id"] and w["segment_id"] not in item["segments"]:
            item["segments"].append(w["segment_id"])
    standard = [("editorial: final pacing, music edit and emotional read", "editorial",
                 "Automated checks cannot judge rhythm, performance or whether the cut feels right.")]
    if any(a["action"] in ("swap_music", "use_dialogue_stem", "mute_dialogue") for a in plan["repair_history"]):
        standard.append(("legal: confirm the rights clearances this plan relies on", "legal",
                         "Rights-driven repairs were made; legal should confirm the contract data is current."))
    if aud.get("dialect_audience"):
        standard.append(("cultural reviewer from the region: sign off representation and subtitles", "cultural",
                         "Dialect treatment and cultural framing need a native reviewer; lexicon checks are not enough."))
    for key, owner, reason in standard:
        out.setdefault(key, {"approval": key, "owner": owner, "reasons": [reason], "segments": []})
    return list(out.values())


def _cost(ctx, plan, aud, shared_usd, spot_checked):
    own = ctx.budget.spent_for(aud["audience_id"])
    sheet = ctx.pkg.cost_sheet["models"]
    calls = [e for e in ctx.budget.ledger if e.get("audience") == aud["audience_id"] and e["type"] == "model_call"]
    tokens_in = sum(e["input_tokens"] for e in calls)
    tokens_out = sum(e["output_tokens"] for e in calls)
    cheaper = "claude-sonnet-5-5"
    cheaper_usd = (tokens_in * sheet[cheaper]["input_per_mtok"] + tokens_out * sheet[cheaper]["output_per_mtok"]) / 1e6
    return {
        "estimated_usd": round(own + shared_usd, 6),
        "breakdown": {"this_trailer_usd": own, "shared_story_analysis_usd": round(shared_usd, 6),
                      "model_calls": [{k: e[k] for k in ("task", "model", "input_tokens", "output_tokens", "usd")} for e in calls],
                      "keyframe_spot_check": spot_checked},
        "budget_exceeded": not ctx.budget.summary()["within_budget"],
        "lower_cost_fallback": [
            {"strategy": f"Proposal from {cheaper} instead of the preferred model; same verifier and repair",
             "estimated_usd": round(cheaper_usd + shared_usd, 6),
             "tradeoff": "Somewhat weaker creative drafts; the verifier guarantees the same safety floor."},
            {"strategy": "Deterministic template planner (no model call), cached story map, no keyframe spot-check",
             "estimated_usd": 0.0,
             "tradeoff": "Formulaic beat order and generic promise; description/footage mismatches go straight to a human."},
        ],
    }


def distinctness(plans: dict) -> list[dict]:
    rows, ids = [], sorted(plans)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            ra = {(s["video"], s["source_in"]) for s in plans[a]["segments"]}
            rb = {(s["video"], s["source_in"]) for s in plans[b]["segments"]}
            j = len(ra & rb) / len(ra | rb) if ra | rb else 0.0
            rows.append({"pair": [a, b], "shared_clips": len(ra & rb), "jaccard": round(j, 3), "too_similar": j > 0.5})
    return rows


def input_fingerprint(pkg) -> dict:
    return {k: hashlib.sha256(json.dumps(v, sort_keys=True).encode()).hexdigest()[:16] for k, v in pkg.raw.items()}


def _remembered_analysis(pkg, out_dir):
    """Story analysis from an earlier run in out_dir, if it was made for this exact episode package."""
    state_path = Path(out_dir) / "run_state.json"
    if not state_path.exists():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if state.get("input_fingerprint", {}).get("episode") != input_fingerprint(pkg)["episode"]:
        return None
    return state.get("story_analysis_cache") or None


def run(data_dir, out_dir, audiences=None, mode=None, unavailable=(), episode_path=None, audiences_path=None,
        model_chain=None, replay_dir=None) -> dict:
    pkg = Package.load(data_dir, episode_path, audiences_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx = make_context(pkg, mode, unavailable, recovery_analysis=_remembered_analysis(pkg, out_dir),
                       model_chain=model_chain, replay_dir=replay_dir, record_dir=out_dir / "model_responses")
    audiences = audiences or pkg.config["audiences"]
    unknown = [a for a in audiences if pkg.audience(a) is None]
    if unknown:
        raise PackageError(f"Unknown audience(s) {unknown}; defined: {sorted(pkg.audiences)}")

    shared_usd = sum(e["usd"] for e in ctx.budget.ledger if e.get("audience") is None) / max(len(audiences), 1)
    plans = {}
    for aud_id in audiences:
        aud = pkg.audience(aud_id)
        plan = ctx.planner.plan(aud)
        result = verify_and_repair(ctx, plan, aud)
        plans[aud_id] = finalize(ctx, plan, aud, result, shared_usd)

    write_outputs(ctx, plans, out_dir, data_dir)
    return {"plans": plans, "context": ctx}


def write_outputs(ctx, plans, out_dir, data_dir, report_name="validation_report.md", title=None):
    out_dir = Path(out_dir)
    dump = lambda name, obj: (out_dir / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    dump("story_map.json", ctx.story_map)
    dump("spoiler_map.json", ctx.spoiler_map)
    dump("constraint_map.json", ctx.constraint_map)
    dump("audience_insight_review.json", ctx.bias_review)
    for aud_id, plan in plans.items():
        dump(f"{aud_id}_trailer.json", plan)
    summary = {"run_id": ctx.pkg.config["run_id"], "mode": ctx.router.mode,
               "trailers": {a: {"trailer_id": p["trailer_id"], "status": p["validation"]["status"],
                                "ready_for_editor": p["ready_for_editor"], "duration_seconds": p["duration_seconds"],
                                "segments": len(p["segments"])} for a, p in plans.items()},
               "distinctness": distinctness(plans), "budget": ctx.budget.summary()}
    dump("run_summary.json", summary)
    dump("run_state.json", {"run_id": ctx.pkg.config["run_id"], "data_dir": str(data_dir), "mode": ctx.router.mode,
                            "input_fingerprint": input_fingerprint(ctx.pkg), "story_analysis_cache": ctx.analysis})
    ctx.log.write(out_dir / "decision_log.jsonl")
    write_validation_report(ctx, plans, summary, out_dir / report_name, title=title)
    build_dashboard(out_dir)
    return summary
