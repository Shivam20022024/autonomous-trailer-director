"""Loads the supplied material and provides lookups over it.

The raw JSON is kept alongside the parsed models so change events can patch it
and rebuild a new Package without touching the files on disk.
"""
import copy
import json
from datetime import date
from pathlib import Path

from .models import Episode
from .timecode import overlaps

FILES = {
    "episode": "episode_package.json",
    "subtitles": "subtitles.json",
    "policies": "policies.json",
    "contracts": "contracts.json",
    "audiences": "audiences.json",
    "profiles": "audience_profiles.json",
    "historic": "historic_performance.json",
    "cost_sheet": "cost_sheet.json",
    "config": "config.json",
}


class PackageError(Exception):
    pass


class Package:
    def __init__(self, raw: dict, data_dir: Path | None = None):
        missing = [k for k in FILES if k not in raw]
        if missing:
            raise PackageError(f"Missing input material: {missing}")
        self.raw = raw
        self.data_dir = data_dir
        self.episode = Episode.model_validate(raw["episode"])
        self.subtitles = raw["subtitles"]
        self.policies = raw["policies"]
        self.contracts = raw["contracts"]
        self.audiences = {a["audience_id"]: a for a in raw["audiences"]}
        self.profiles = raw["profiles"]["profiles"]
        self.historic = raw["historic"]
        self.cost_sheet = raw["cost_sheet"]
        self.config = raw["config"]

        self.scenes = {s.scene_id: s for s in self.episode.scenes}
        self.characters = {c.character_id: c for c in self.episode.characters}
        self.lines = {l.line_id: (s, l) for s in self.episode.scenes for l in s.dialogue}
        self.moments = {m.moment_id: (s, m) for s in self.episode.scenes for m in s.moments}
        self.music = {m["track_id"]: m for m in self.contracts["music"]}
        self.actors = {a["actor_id"]: a for a in self.contracts["actors"]}
        self._check_integrity()

    @classmethod
    def load(cls, data_dir, episode_path=None, audiences_path=None) -> "Package":
        data_dir = Path(data_dir)
        raw = {}
        for key, name in FILES.items():
            path = data_dir / name
            if key == "episode" and episode_path:
                path = Path(episode_path)
            if key == "audiences" and audiences_path:
                path = Path(audiences_path)
            if not path.exists():
                raise PackageError(f"Required input not found: {path}")
            raw[key] = json.loads(path.read_text(encoding="utf-8"))
        return cls(raw, data_dir)

    def with_raw(self, raw: dict) -> "Package":
        return Package(raw, self.data_dir)

    def raw_copy(self) -> dict:
        return copy.deepcopy(self.raw)

    def _check_integrity(self):
        problems = []
        for c in self.characters.values():
            if c.actor_id not in self.actors:
                problems.append(f"character {c.character_id} has no actor contract ({c.actor_id})")
        for s in self.scenes.values():
            for ch in s.characters_present:
                if ch not in self.characters:
                    problems.append(f"{s.scene_id}: unknown character {ch}")
        for track in self.subtitles["tracks"]:
            if track not in self.subtitles["cues"]:
                problems.append(f"subtitle track {track} has no cues")
        if problems:
            raise PackageError("; ".join(problems))

    # ---- lookups ------------------------------------------------------
    def scene(self, scene_id):
        return self.scenes.get(scene_id)

    def audience(self, audience_id):
        return self.audiences.get(audience_id)

    def actor_for(self, character_id):
        ch = self.characters.get(character_id)
        return self.actors.get(ch.actor_id) if ch else None

    def cue(self, track, line_id):
        return self.subtitles["cues"].get(track, {}).get(line_id)

    def resolve_ref(self, ref: str):
        """Resolve a source reference to {kind, id, scene_id, start, end, text}."""
        if not isinstance(ref, str) or ":" not in ref:
            return None
        kind, ident = ref.split(":", 1)
        if kind == "scene" and ident in self.scenes:
            s = self.scenes[ident]
            return {"kind": kind, "id": ident, "scene_id": ident, "start": s.start_s, "end": s.end_s,
                    "text": s.human_description}
        if kind == "line" and ident in self.lines:
            s, l = self.lines[ident]
            return {"kind": kind, "id": ident, "scene_id": s.scene_id, "start": l.start_s, "end": l.end_s, "text": l.text}
        if kind == "moment" and ident in self.moments:
            s, m = self.moments[ident]
            return {"kind": kind, "id": ident, "scene_id": s.scene_id, "start": m.start_s, "end": m.end_s,
                    "text": m.description}
        if kind == "cast" and ident in self.actors:  # an actor id names exactly one character
            ident = self.actors[ident]["plays"]
        if kind == "cast" and ident in self.characters:
            return {"kind": kind, "id": ident, "scene_id": None, "start": None, "end": None,
                    "text": self.characters[ident].description}
        return None

    def ref_exists(self, ref: str) -> bool:
        if self.resolve_ref(ref):
            return True
        kind, _, ident = (ref or "").partition(":")
        if kind == "contract":
            return ident in self.music or ident in self.actors
        if kind == "policy":
            return ident in self.policies["rating_policies"]
        if kind == "insight":
            return any(i["insight_id"] == ident for p in self.profiles.values() for i in p["insights"])
        if kind == "cue":
            track, _, line = ident.partition(":")
            return self.cue(track, line) is not None
        if kind == "historic":
            return ident in self.historic.get("scene_scores", {})
        return False

    def lines_in(self, scene, t0, t1):
        return [l for l in scene.dialogue if overlaps(l.start_s, l.end_s, t0, t1)]

    def moments_in(self, scene, t0, t1):
        return [m for m in scene.moments if overlaps(m.start_s, m.end_s, t0, t1)]

    def on_screen(self, scene, t0, t1) -> set[str]:
        """Characters visible in a clip, from shot and line metadata.

        When no shot or line metadata covers the clip we fall back to everyone
        present in the scene (conservative for rights checks).
        """
        chars, covered = set(), False
        for m in self.moments_in(scene, t0, t1):
            chars |= set(m.characters)
            covered = True
        for l in self.lines_in(scene, t0, t1):
            chars.add(l.speaker)
            covered = True
        return chars if covered else set(scene.characters_present)

    def music_problems(self, track_id, market) -> list[str]:
        """Why a track may not be used in a promo for this market (empty list = usable)."""
        t = self.music.get(track_id)
        if t is None:
            return [f"music track '{track_id}' has no contract"]
        out = []
        if not t["cleared_for_promos"]:
            out.append(f"{track_id} ('{t['title']}') is not cleared for promotional use")
        if market not in t["territories"]:
            out.append(f"{track_id} ('{t['title']}') is not cleared in market '{market}'")
        campaign_end = date.fromisoformat(self.config["campaign_window"]["end"])
        if date.fromisoformat(t["expires"]) < campaign_end:
            out.append(f"{track_id} ('{t['title']}') rights expire {t['expires']}, before campaign end {campaign_end}")
        return out

    def usable_tracks(self, market) -> list[str]:
        return [tid for tid in self.music if not self.music_problems(tid, market)]
