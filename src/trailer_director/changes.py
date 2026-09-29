"""Respond to changes after planning.

A change event patches the supplied material (contract, policy, subtitle, scene
metadata, audience data), requests a creative change (marketing), or reports a
model outage. The system:

1. maps the patch to changed entities (music:music-02, cue:dialect_a:d08_1, ...),
2. finds the trailers and segments whose recorded `depends_on` includes them,
3. re-runs every check on every trailer (cheap, and catches dependency misses),
4. repairs only what now fails, and
5. writes a revision record saying what changed and why.

Each event is applied to the base run independently, not cumulatively.
"""
import copy
import json
from pathlib import Path

from .dashboard import build_dashboard
from .logbook import DecisionLog
from .orchestrator import finalize, make_context, verify_and_repair
from .package import Package

DIFF_FIELDS = ("video", "source_ref", "source_in", "source_out", "audio", "music", "text_card", "voice_over")


def _select(container, key):
    if isinstance(key, dict):
        (k, v), = key.items()
        for i, item in enumerate(container):
            if item.get(k) == v:
                return i
        raise ValueError(f"No element with {k}={v!r}")
    return key


def _entity(file, path):
    head = path[0] if path else None
    if file == "contracts" and head == "music":
        return f"music:{path[1]['track_id']}"
    if file == "contracts" and head == "actors":
        return f"actor:{path[1]['actor_id']}"
    if file == "policies":
        return f"policy:{path[1]}" if head == "rating_policies" and len(path) > 1 else "policy:*"
    if file == "subtitles" and head == "cues":
        return f"cue:{path[1]}:{path[2]}"
    if file == "episode" and head == "scenes":
        return f"scene:{path[1]['scene_id']}"
    if file == "profiles":
        return f"audience:{path[1]}"
    if file == "audiences":
        return f"audience:{head['audience_id']}"
    return f"{file}:*"


def apply_patch(raw: dict, patch: list[dict]) -> tuple[set[str], list[dict]]:
    entities, applied = set(), []
    for op in patch:
        target = raw[op["file"]]
        for key in op["path"][:-1]:
            target = target[_select(target, key)]
        last = _select(target, op["path"][-1])
        old = target.get(last) if isinstance(target, dict) else target[last]
        target[last] = op["value"]
        entities.add(_entity(op["file"], op["path"]))
        applied.append({"file": op["file"], "path": op["path"], "old": old, "new": op["value"]})
    return entities, applied


def impact(plan: dict, entities: set[str], rating_policy: str) -> tuple[list[str], list[str]]:
    """Segments and plan-level decisions whose recorded dependencies include a changed entity."""
    if any(e.endswith(":*") for e in entities):
        return [s["segment_id"] for s in plan["segments"]], sorted(entities)
    plan_deps = {f"audience:{plan['audience_id']}", f"music:{plan['music_plan']['bed_track']}", f"policy:{rating_policy}"}
    segs = [s["segment_id"] for s in plan["segments"] if set(s["depends_on"]) & entities]
    return segs, sorted(plan_deps & entities)


def _view(seg):
    v = {k: seg.get(k) for k in DIFF_FIELDS}
    v["subtitle_track"] = (seg.get("subtitle") or {}).get("track")
    v["subtitle_text"] = (seg.get("subtitle") or {}).get("text")
    return v


def diff_plans(before: dict, after: dict) -> list[dict]:
    b = {s["segment_id"]: s for s in before["segments"]}
    a = {s["segment_id"]: s for s in after["segments"]}
    out = []
    for sid in list(dict.fromkeys([*b, *a])):
        if sid not in a:
            out.append({"segment_id": sid, "change": "removed", "before": _view(b[sid])})
        elif sid not in b:
            out.append({"segment_id": sid, "change": "added", "after": _view(a[sid])})
        else:
            vb, va = _view(b[sid]), _view(a[sid])
            fields = {k: {"before": vb[k], "after": va[k]} for k in vb if vb[k] != va[k]}
            if fields:
                out.append({"segment_id": sid, "change": "modified", "fields": fields})
    if before["music_plan"]["bed_track"] != after["music_plan"]["bed_track"]:
        out.append({"segment_id": None, "change": "music_bed",
                    "fields": {"bed_track": {"before": before["music_plan"]["bed_track"], "after": after["music_plan"]["bed_track"]}}})
    return out


def apply_change(run_dir, event_path, data_dir=None, out_dir=None) -> dict:
    run_dir = Path(run_dir)
    state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    event_id, etype = event["event_id"], event["type"]
    out_dir = Path(out_dir) if out_dir else run_dir / "changes" / event_id
    out_dir.mkdir(parents=True, exist_ok=True)

    base = Package.load(data_dir or state["data_dir"])
    plans_before = {}
    for aud_id in base.audiences:
        p = run_dir / f"{aud_id}_trailer.json"
        if p.exists():
            plans_before[aud_id] = json.loads(p.read_text(encoding="utf-8"))

    log = DecisionLog(f"{state['run_id']}:{event_id}")
    log.record("change_event", event.get("description", ""), event_type=etype, event_id=event_id)
    raw = base.raw_copy()
    entities, applied = apply_patch(raw, event.get("patch", []))
    pkg = base.with_raw(raw)
    unavailable = event.get("models", []) if etype == "model_outage" else []
    if etype == "model_outage":
        entities |= {f"model:{m}" for m in unavailable}
    log.record("change_entities", f"Changed entities: {sorted(entities) or 'none'}", patch=applied)
    ctx = make_context(pkg, mode=state["mode"], unavailable=unavailable, log=log,
                       cached_analysis=state["story_analysis_cache"])

    if etype == "marketing_request":
        report = _marketing_request(ctx, event, plans_before, out_dir)
    else:
        report = _revise(ctx, event, entities, plans_before, out_dir)
    if etype == "model_outage":
        remaining = [m for m in pkg.config["model_chain"] if m not in unavailable]
        report["model_fallback"] = {"unavailable": unavailable, "remaining_chain": remaining,
                                    "next_planning_source": remaining[0] if remaining else "deterministic planner"}
        report["outcome"] = ("No existing plan depends on model availability; plans stand unchanged. Future planning "
                             f"uses {report['model_fallback']['next_planning_source']}.")
    report.update(event_id=event_id, type=etype, description=event.get("description", ""),
                  changed_entities=sorted(entities), patch=applied)
    (out_dir / "constraint_map_after.json").write_text(json.dumps(ctx.constraint_map, indent=2, ensure_ascii=False) + "\n",
                                                       encoding="utf-8")
    report["report_path"] = str(out_dir / "change_report.md")
    (out_dir / "change_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.write(out_dir / "decision_log.jsonl")
    _write_md(report, out_dir / "change_report.md")
    if (run_dir / "run_summary.json").exists():
        build_dashboard(run_dir)  # the run's dashboard lists every change applied to it
    return report


def _revise(ctx, event, entities, plans_before, out_dir) -> dict:
    trailers, any_changed = [], False
    for aud_id, before in plans_before.items():
        aud = ctx.pkg.audience(aud_id)
        segs, plan_level = impact(before, entities, aud["rating_policy"])
        plan = copy.deepcopy(before)
        check = ctx.verifier.verify_plan(plan)
        impacted = bool(segs or plan_level)
        row = {"trailer_id": before["trailer_id"], "audience_id": aud_id, "impacted": impacted,
               "impacted_segments": segs, "plan_level_dependencies": plan_level,
               "status_before": before["validation"]["status"], "rechecked": True}
        if not impacted and check["errors"]:
            ctx.log.record("dependency_index_miss", "Re-check found errors in a trailer the dependency index marked "
                           "unaffected; repairing it anyway", aud_id, errors=[e["check_id"] for e in check["errors"]])
            impacted = row["impacted"] = True
        if not impacted:
            ctx.log.record("impact", f"{before['trailer_id']} does not depend on {sorted(entities)}; re-check "
                           f"{check['status']}; left unchanged", aud_id)
            trailers.append({**row, "changed_segments": 0, "clip_changes": 0, "status_after": check["status"], "diff": []})
            continue
        ctx.log.record("impact", f"{before['trailer_id']}: segments {segs} and plan-level {plan_level} depend on the change",
                       aud_id)
        n_hist = len(plan["repair_history"])
        result = verify_and_repair(ctx, plan, aud)
        actions = plan["repair_history"][n_hist:]
        diff = diff_plans(before, plan)
        warnings_changed = {(w["check_id"], w["segment_id"]) for w in result["warnings"]} != \
                           {(w["check_id"], w["segment_id"]) for w in before["validation"]["warnings"]}
        if diff or warnings_changed or result["status"] != before["validation"]["status"]:
            any_changed = True
            plan["version"] = before["version"] + 1
            plan["trailer_id"] = f"{aud_id}_v{plan['version']}"
            changed_ids = {d["segment_id"] for d in diff if d["segment_id"]}
            spot = sum(s.get("duration_seconds") or 0 for s in plan["segments"] if s["segment_id"] in changed_ids)
            finalize(ctx, plan, aud, result, spot_check_seconds=spot, keep_cost=True)
            plan["revisions"].append({
                "revision": plan["version"], "event_id": event["event_id"], "event": event.get("description", ""),
                "changed_entities": sorted(entities), "impacted_segments": segs, "plan_level_dependencies": plan_level,
                "changes": diff, "repair_actions": actions,
                "revision_cost_usd": ctx.budget.spent_for(aud_id),
                "status_before": before["validation"]["status"], "status_after": result["status"]})
            (out_dir / f"{aud_id}_trailer_v{plan['version']}.json").write_text(
                json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            ctx.log.record("revision", f"{before['trailer_id']} -> {plan['trailer_id']}: {len(diff)} change(s), "
                           f"status {result['status']}", aud_id)
        old_w = {(w["check_id"], w["segment_id"], w["message"]) for w in before["validation"]["warnings"]}
        clip_fields = {"video", "source_ref", "source_in", "source_out"}
        trailers.append({**row, "changed_segments": len([d for d in diff if d["segment_id"]]),
                         "clip_changes": len([d for d in diff if d["change"] in ("added", "removed")
                                              or (d["change"] == "modified" and clip_fields & set(d["fields"]))]),
                         "new_warnings": [f"{w['check_id']} {w['segment_id'] or 'plan'}: {w['message']}" for w in result["warnings"]
                                          if (w["check_id"], w["segment_id"], w["message"]) not in old_w],
                         "status_after": result["status"], "diff": diff,
                         "repair_actions": actions, "new_trailer_id": plan["trailer_id"] if plan["trailer_id"] != before["trailer_id"] else None,
                         "added_approvals": [a["approval"] for a in plan.get("human_approvals_required", [])
                                             if a["approval"] not in {x["approval"] for x in before["human_approvals_required"]}]})
    outcome = "Revised affected trailers" if any_changed else "No trailer needed revision"
    return {"outcome": outcome, "trailers": trailers}


def _marketing_request(ctx, event, plans_before, out_dir) -> dict:
    aud_id = event["audience"]
    aud = ctx.pkg.audience(aud_id)
    before = plans_before[aud_id]
    req = event["request"]
    plan = copy.deepcopy(before)
    idx = next((i for i, s in enumerate(plan["segments"]) if s["segment_id"] == req.get("segment_id")
                or s["beat"] == req.get("beat")), 0)
    seg = plan["segments"][idx]
    trial = {**seg, "text_card": req["text_card"]}
    problems = [f for f in ctx.verifier.check_segment(trial, aud) if f["severity"] == "error"]
    rows = [{"trailer_id": p["trailer_id"], "audience_id": a, "impacted": a == aud_id, "impacted_segments":
             [seg["segment_id"]] if a == aud_id else [], "changed_segments": 0, "clip_changes": 0,
             "status_before": p["validation"]["status"], "status_after": p["validation"]["status"], "diff": []}
            for a, p in plans_before.items()]
    if problems:
        alternatives = []
        for alt in before.get("alternate_text_cards", []):
            t = {**seg, "text_card": alt}
            if not [f for f in ctx.verifier.check_segment(t, aud) if f["severity"] == "error"]:
                alternatives.append(alt)
        ctx.log.record("marketing_request_rejected", f"Rejected text card '{req['text_card']['text']}': "
                       + "; ".join(f["message"] for f in problems), aud_id)
        return {"outcome": "Request rejected; plan unchanged", "trailers": rows,
                "rejection": {"segment_id": seg["segment_id"], "requested": req["text_card"],
                              "violations": problems, "compliant_alternatives": alternatives,
                              "escalation": "Marketing may appeal to editorial; the verifier will still block the "
                                            "card unless the underlying policy or story facts change."}}
    plan["segments"][idx] = trial
    result = ctx.verifier.verify_plan(plan)
    if result["errors"]:
        ctx.log.record("marketing_request_rejected", "Card passes on its own but breaks the plan", aud_id)
        return {"outcome": "Request rejected; plan unchanged", "trailers": rows,
                "rejection": {"segment_id": seg["segment_id"], "requested": req["text_card"], "violations": result["errors"]}}
    plan["version"] = before["version"] + 1
    plan["trailer_id"] = f"{aud_id}_v{plan['version']}"
    finalize(ctx, plan, aud, result, spot_check_seconds=0, keep_cost=True)
    diff = diff_plans(before, plan)
    plan["revisions"].append({"revision": plan["version"], "event_id": event["event_id"], "event": event.get("description", ""),
                              "changes": diff, "status_after": result["status"]})
    (out_dir / f"{aud_id}_trailer_v{plan['version']}.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    for r in rows:
        if r["audience_id"] == aud_id:
            r.update(changed_segments=1, status_after=result["status"], diff=diff, new_trailer_id=plan["trailer_id"])
    ctx.log.record("marketing_request_accepted", f"Applied text card to {seg['segment_id']}", aud_id)
    return {"outcome": "Request accepted", "trailers": rows}


def _write_md(report, path):
    L = [f"# Change report: {report['event_id']}", "", f"**Type:** {report['type']}  ", f"**Event:** {report['description']}  ",
         f"**Changed entities:** {', '.join(report['changed_entities']) or 'none'}  ", f"**Outcome:** {report['outcome']}", ""]
    for p in report.get("patch", []):
        L.append(f"- Patched `{p['file']}` {p['path']}: `{p['old']}` -> `{p['new']}`")
    L += ["", "| Trailer | Impacted | Impacted segments | Segments touched | Clip changes | Status before | Status after | New version |",
          "|---|---|---|---|---|---|---|---|"]
    for t in report["trailers"]:
        L.append(f"| {t['trailer_id']} | {'yes' if t['impacted'] else 'no'} | {', '.join(t['impacted_segments']) or '-'} | "
                 f"{t['changed_segments']} | {t['clip_changes']} | {t['status_before']} | {t['status_after']} | "
                 f"{t.get('new_trailer_id') or '-'} |")
    L += ["", "All trailers were re-checked in full. 'Segments touched' counts any field change (e.g. a new music bed "
          "inherited by every segment); 'Clip changes' counts segments whose source clip was replaced, trimmed, added or removed.", ""]
    for t in report["trailers"]:
        if not t.get("diff") and not t.get("repair_actions") and not t.get("new_warnings"):
            continue
        L += [f"## {t['trailer_id']}", ""]
        for d in t["diff"]:
            if d["change"] == "modified" or d["change"] == "music_bed":
                for k, v in d["fields"].items():
                    L.append(f"- `{d['segment_id'] or 'plan'}` {k}: `{v['before']}` -> `{v['after']}`")
            else:
                L.append(f"- `{d['segment_id']}` {d['change']}")
        for a in t.get("repair_actions", []):
            L.append(f"- Why ({a['action']}): {'; '.join(a['because'])}")
        for w in t.get("new_warnings", []):
            L.append(f"- New warning: {w}")
        if t.get("added_approvals"):
            L.append(f"- New human approvals: {', '.join(t['added_approvals'])}")
        L.append("")
    if "rejection" in report:
        r = report["rejection"]
        L += ["## Rejected request", "", f"Requested card on `{r['segment_id']}`: \"{r['requested']['text']}\"", ""]
        L += [f"- {v['check_id']}: {v['message']}" for v in r["violations"]]
        if r.get("compliant_alternatives"):
            L.append(f"- Compliant alternatives: {', '.join(repr(a['text']) for a in r['compliant_alternatives'])}")
        L.append(f"- {r.get('escalation', '')}")
        L.append("")
    if "model_fallback" in report:
        m = report["model_fallback"]
        L += ["## Model fallback", "", f"- Unavailable: {', '.join(m['unavailable'])}",
              f"- Remaining chain: {', '.join(m['remaining_chain']) or 'none'}; next planning source: {m['next_planning_source']}", ""]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
