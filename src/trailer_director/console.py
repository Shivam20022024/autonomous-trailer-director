"""Live console output: prints decisions as they are logged."""
import os
import sys

# kind -> (tag, colour). Kinds not listed here are not printed (they stay in decision_log.jsonl).
STYLE = {
    "ingest": ("load", "cyan"),
    "change_event": ("event", "cyan"),
    "change_entities": ("event", "cyan"),
    "model_call": ("model", "blue"),
    "analysis_reused": ("model", "blue"),
    "model_unavailable": ("warn", "yellow"),
    "model_output_invalid": ("warn", "yellow"),
    "model_output_normalized": ("warn", "yellow"),
    "budget_skip": ("budget", "yellow"),
    "fallback": ("warn", "yellow"),
    "claim_rejected": ("reject", "red"),
    "spoiler_backfill": ("guard", "magenta"),
    "description_mismatch": ("flag", "yellow"),
    "injection_flag": ("flag", "yellow"),
    "insight_excluded": ("bias", "magenta"),
    "proposal": ("draft", "blue"),
    "verification": ("check", None),
    "hallucination_rejected": ("reject", "red"),
    "high_performing_idea_rejected": ("reject", "red"),
    "repair": ("repair", "green"),
    "repair_stalled": ("stall", "red"),
    "finalize": ("done", None),
    "impact": ("impact", "cyan"),
    "dependency_index_miss": ("warn", "yellow"),
    "revision": ("revise", "green"),
    "marketing_request_rejected": ("reject", "red"),
    "marketing_request_accepted": ("accept", "green"),
}
CODES = {"red": 31, "green": 32, "yellow": 33, "blue": 34, "magenta": 35, "cyan": 36, "bold": 1, "dim": 2}


class ConsolePrinter:
    def __init__(self, stream=None, width=110):
        self.stream = stream or sys.stdout
        self.width = width
        self.colour = hasattr(self.stream, "isatty") and self.stream.isatty() and not os.environ.get("NO_COLOR")
        if self.colour and os.name == "nt":
            os.system("")  # enables ANSI escape handling in the Windows console
        self._audience = object()

    def _c(self, text, colour):
        return f"\033[{CODES[colour]}m{text}\033[0m" if self.colour and colour else text

    def __call__(self, e):
        style = STYLE.get(e["kind"])
        if not style:
            return
        if e.get("audience") != self._audience and e["kind"] not in ("model_output_normalized",):
            self._audience = e.get("audience")
            title = f" {self._audience.upper()} " if self._audience else " SHARED ANALYSIS "
            self.stream.write("\n" + self._c(f"== {title.strip()} " + "=" * (60 - len(title)), "bold") + "\n")
        tag, colour = style
        msg = self._message(e)
        if e["kind"] == "verification":
            colour = "red" if "FAIL" in msg else "yellow" if "WARNINGS" in msg else "green"
        if e["kind"] == "finalize":
            colour = "red" if "FAIL" in msg else "green"
        line = f"  {self._c(f'{tag:>7}', colour)}  {msg}"
        self.stream.write(line[: self.width + 20 if self.colour else self.width] + "\n")
        self.stream.flush()

    def _message(self, e):
        k = e["kind"]
        if k == "model_call":
            return f"{e.get('task')} <- {e.get('model')} ({e.get('mode')}), {e.get('input_tokens')} in / " \
                   f"{e.get('output_tokens')} out tokens, ${e.get('usd', 0):.4f}"
        if k == "repair":
            because = (e.get("because") or [""])[0]
            return f"{e.get('action')} {e.get('segment_id') or 'plan'}: {because}"
        return e["message"]


def install(quiet=False):
    """Stream decisions to stdout unless quiet. Also makes printing safe on legacy Windows code pages."""
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(errors="replace")
    from .logbook import DecisionLog
    DecisionLog.echo = None if quiet else ConsolePrinter()
