"""Timecode parsing and formatting (HH:MM:SS.mmm)."""
import re

_TC = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3})$")


def parse_tc(tc: str) -> float:
    m = _TC.match(tc or "")
    if not m:
        raise ValueError(f"Malformed timecode {tc!r}; expected HH:MM:SS.mmm")
    h, mi, s, ms = map(int, m.groups())
    if mi > 59 or s > 59:
        raise ValueError(f"Out-of-range timecode {tc!r}")
    return h * 3600 + mi * 60 + s + ms / 1000


def fmt_tc(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def overlaps(a0: float, a1: float, b0: float, b1: float) -> bool:
    return a0 < b1 and b0 < a1
