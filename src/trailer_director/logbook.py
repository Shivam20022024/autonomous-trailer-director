"""Structured decision log.

Entries carry a sequence number rather than wall-clock time so that repeated
runs on the same inputs produce byte-identical logs.
"""
import json
from pathlib import Path


class DecisionLog:
    # Set by the CLI to stream decisions to the console as they happen; None keeps runs silent (tests, library use).
    echo = None

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.entries: list[dict] = []

    def record(self, kind: str, message: str, audience: str | None = None, **details) -> dict:
        entry = {"seq": len(self.entries) + 1, "run_id": self.run_id, "kind": kind,
                 "audience": audience, "message": message}
        entry.update({k: v for k, v in details.items() if v is not None})
        self.entries.append(entry)
        if DecisionLog.echo:
            DecisionLog.echo(entry)
        return entry

    def of_kind(self, kind: str) -> list[dict]:
        return [e for e in self.entries if e["kind"] == kind]

    def write(self, path: Path):
        with open(path, "w", encoding="utf-8") as f:
            for e in self.entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
