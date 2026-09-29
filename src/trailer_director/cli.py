"""Command-line interface.

  run     plan, verify and repair trailers for one or more audiences
  change  apply a change event (contract, policy, subtitle, metadata, marketing
          request, model outage) to a previous run and revise only what it affects
  verify  check an existing trailer EDL against the supplied material
  dashboard  (re)build and open <run>/dashboard.html
"""
import argparse
import json
import sys
from pathlib import Path

from .package import PackageError


def _print_summary(summary):
    for aud, t in summary["trailers"].items():
        print(f"  {t['trailer_id']:<24} {t['status']:<20} ready_for_editor={t['ready_for_editor']!s:<5} "
              f"{t['duration_seconds']}s, {t['segments']} segments")
    b = summary["budget"]
    print(f"  budget: {b['model_calls']}/{b['max_model_calls']} calls, ${b['estimated_usd']:.4f}/${b['max_total_usd']:.2f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="trailer_director", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet", action="store_true", help="only print the final summary, not each decision")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="plan trailers")
    r.add_argument("--data", default="data", help="directory with the supplied material")
    r.add_argument("--episode", help="episode package JSON (overrides <data>/episode_package.json)")
    r.add_argument("--audience-defs", help="audience definitions JSON (overrides <data>/audiences.json)")
    r.add_argument("--audiences", help="comma-separated audience ids (default: all in config)")
    r.add_argument("--out", default="sample_run")
    r.add_argument("--mode", choices=["mock", "live"], help="mock = replay recorded model output (default from config)")
    r.add_argument("--unavailable-model", action="append", default=[], help="simulate an outage of this model")
    r.add_argument("--model-chain", help="comma-separated models to try in order, e.g. gpt-5,gpt-5-mini "
                   "(claude-* models use ANTHROPIC_API_KEY, others OPENAI_API_KEY)")
    r.add_argument("--replay-dir", help="mock mode: recorded responses to replay (default <data>/replay); "
                   "live runs record theirs to <out>/model_responses")

    c = sub.add_parser("change", help="apply a change event to a previous run")
    c.add_argument("--run", default="sample_run", help="directory of the run to revise")
    c.add_argument("--event", required=True, help="change event JSON")
    c.add_argument("--data", help="data directory (default: the one recorded in the run)")
    c.add_argument("--out", help="output directory (default: <run>/changes/<event_id>)")

    d = sub.add_parser("dashboard", help="build and open the HTML dashboard for a run")
    d.add_argument("--run", default="sample_run")
    d.add_argument("--no-open", action="store_true", help="only write the file")

    v = sub.add_parser("verify", help="verify an existing trailer EDL")
    v.add_argument("plan", help="trailer JSON to verify")
    v.add_argument("--data", default="data")

    args = ap.parse_args(argv)
    from .console import install
    install(quiet=args.quiet or args.cmd == "dashboard")
    try:
        if args.cmd == "run":
            from .orchestrator import run
            auds = args.audiences.split(",") if args.audiences else None
            chain = args.model_chain.split(",") if args.model_chain else None
            res = run(args.data, args.out, auds, args.mode, args.unavailable_model, args.episode, args.audience_defs, chain, args.replay_dir)
            summary = json.loads((Path(args.out) / "run_summary.json").read_text(encoding="utf-8"))
            print(f"\nWrote plans and reports to {args.out}/")
            _print_summary(summary)
            print(f"  dashboard: {Path(args.out) / 'dashboard.html'}  (open it, or: python run_director.py dashboard --run {args.out})")
            return 0 if all(p["ready_for_editor"] for p in res["plans"].values()) else 2
        if args.cmd == "change":
            from .changes import apply_change
            report = apply_change(args.run, args.event, args.data, args.out)
            print(f"\nEvent {report['event_id']} ({report['type']}): {report['outcome']}")
            for t in report["trailers"]:
                print(f"  {t['trailer_id']:<20} impacted={t['impacted']!s:<5} segments_touched={t['changed_segments']:<2} "
                      f"clip_changes={t['clip_changes']:<2} status={t['status_after']}"
                      + (f" -> {t['new_trailer_id']}" if t.get("new_trailer_id") else ""))
            print(f"Report: {report['report_path']}")
            return 0
        if args.cmd == "dashboard":
            from .dashboard import build_dashboard
            if not (Path(args.run) / "run_summary.json").exists():
                raise FileNotFoundError(f"{args.run} is not a run directory; run `run --out {args.run}` first")
            path = build_dashboard(args.run).resolve()
            print(f"Dashboard: {path}")
            if not args.no_open:
                import webbrowser
                webbrowser.open(path.as_uri())
            return 0
        if args.cmd == "verify":
            from .orchestrator import make_context
            from .package import Package
            pkg = Package.load(args.data)
            ctx = make_context(pkg)
            plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
            result = ctx.verifier.verify_plan(plan)
            print(f"{plan.get('trailer_id')}: {result['status']}")
            for f in result["errors"] + result["warnings"]:
                print(f"  [{f['severity']}] {f['check_id']} {f['segment_id'] or 'plan'}: {f['message']}")
            return 0 if result["status"] != "FAIL" else 2
    except (PackageError, FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 1
