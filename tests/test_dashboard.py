"""The dashboard and live console are generated from the run and must work offline."""
import io
import json
import re

from trailer_director.console import ConsolePrinter
from trailer_director.dashboard import build_dashboard


def test_dashboard_is_self_contained_and_embeds_the_run(base_run):
    out, res = base_run
    html = build_dashboard(out).read_text(encoding="utf-8")
    assert not re.findall(r'(?:src|href)="https?://', html), "dashboard must not load anything from the network"
    data = json.loads(re.search(r"const D = (\{.*?\});\n", html, re.S).group(1).replace("<\\/", "</"))
    assert set(data["trailers"]) == set(res["plans"])
    assert data["trailers"]["family"]["trailer_id"] == res["plans"]["family"]["trailer_id"]
    assert len(data["log"]) == len(res["context"].log.entries)


def test_console_prints_decisions_as_they_happen():
    buf = io.StringIO()
    p = ConsolePrinter(stream=buf)
    p({"kind": "repair", "audience": "family", "message": "x", "action": "replace_clip", "segment_id": "family_s05",
       "because": ["RGT-003: voice not cleared"]})
    p({"kind": "strategy", "audience": "family", "message": "not shown"})
    text = buf.getvalue()
    assert "FAMILY" in text and "replace_clip family_s05: RGT-003" in text and "not shown" not in text
