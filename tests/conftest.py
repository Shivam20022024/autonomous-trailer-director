import json
import shutil
from pathlib import Path

import pytest

from trailer_director.orchestrator import make_context, run
from trailer_director.package import Package

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="session")
def data_dir():
    return DATA


@pytest.fixture(scope="session")
def ctx():
    return make_context(Package.load(DATA))


@pytest.fixture(scope="session")
def base_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("base_run")
    res = run(DATA, out)
    return out, res


@pytest.fixture
def data_copy(tmp_path):
    """A writable copy of the data directory, for tests that change inputs."""
    dst = tmp_path / "data"
    shutil.copytree(DATA, dst)
    return dst


def edit_json(path: Path, fn):
    obj = json.loads(path.read_text(encoding="utf-8"))
    fn(obj)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def segment(ctx, audience_id, ref=None, video=None, tc_in=None, tc_out=None, audio=None, **extra):
    """Build a grounded segment the way the planner would, from a line/moment ref or explicit timecodes."""
    aud = ctx.pkg.audience(audience_id)
    if ref and ref.split(":")[0] in ("line", "moment"):
        r = ctx.pkg.resolve_ref(ref)
        from trailer_director.timecode import fmt_tc
        video = video or r["scene_id"]
        tc_in = tc_in or fmt_tc(r["start"])
        tc_out = tc_out or fmt_tc(r["end"])
        audio = audio or ("dialogue_and_music" if ref.startswith("line:") else "music_only")
    spec = {"beat": "test", "video": video, "source_ref": ref, "source_in": tc_in, "source_out": tc_out,
            "audio": audio or "music_only", **extra}
    return ctx.planner.ground_segment(aud, spec, f"{audience_id}_t01", 1, extra.pop("bed", "music-01"))


def errors(findings, check=None):
    return [f for f in findings if f["severity"] == "error" and (check is None or f["check_id"] == check)]


def warnings(findings, check=None):
    return [f for f in findings if f["severity"] == "warning" and (check is None or f["check_id"] == check)]
