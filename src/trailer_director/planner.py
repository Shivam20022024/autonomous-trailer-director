"""Planner: audience strategy -> creative proposal -> grounded edit decision list.

The creative proposal comes from a model (live or replayed) and is untrusted.
Grounding only fills in facts derived from the source (dialogue text, subtitle
cues, dependencies); it does not fix or filter the model's choices. Filtering
is the verifier's job, and replacement is the repair step's job.
"""
from dataclasses import dataclass

from .bias import usable_insights
from .llm import ModelUnavailable
from .text_rules import description_tags
from .timecode import fmt_tc, parse_tc

MUSIC_AUDIO = ("dialogue_and_music", "music_only")
AUDIBLE = ("original_mix", "dialogue_and_music", "dialogue_only")


@dataclass
class Candidate:
    ref: str
    scene_id: str
    start: float
    end: float
    kind: str
    tags: frozenset
    description: str


class Planner:
    def __init__(self, pkg, story_map, spoiler_map, constraint_map, bias_review, verifier, router, log):
        self.pkg = pkg
        self.story_map = story_map
        self.spoiler_map = spoiler_map
        self.constraint_map = constraint_map
        self.bias_review = bias_review
        self.verifier = verifier
        self.router = router
        self.log = log

    # ---- strategy -------------------------------------------------------
    def build_brief(self, aud: dict) -> dict:
        usable = usable_insights(self.bias_review, aud["audience_id"])
        excluded = [r for r in self.bias_review.get(aud["audience_id"], []) if not r["usable"]]
        for r in excluded:
            self.log.record("insight_excluded", f"Insight {r['insight_id']} excluded: {'; '.join(r['flags'])}",
                            aud["audience_id"], insight=r["insight_id"])
        elig = self.constraint_map["scene_eligibility"][aud["audience_id"]]
        return {
            "audience_id": aud["audience_id"], "label": aud["label"], "goal": aud["goal"],
            "special_care": aud["special_care"], "market": aud["market"],
            "rating_rules": self.pkg.policies["rating_policies"][aud["rating_policy"]]["rules"],
            "subtitle_track": aud["subtitle_track"], "target_duration_seconds": aud["target_duration_seconds"],
            "music_moods": aud["music_moods"], "usable_insights": usable,
            "excluded_insight_ids": [r["insight_id"] for r in excluded],
            "blocked_scenes": sorted(s for s, v in elig.items() if v["status"] == "blocked"),
            "cleared_music": self.pkg.usable_tracks(aud["market"]),
        }

    def _proposal_payload(self, brief):
        sm = self.story_map
        return {"brief": brief,
                "story_map": {k: sm[k] for k in ("characters", "relationships", "events", "emotional_turns", "scene_index")},
                "protected_facts": [f["statement"] for f in self.spoiler_map["protected_facts"]],
                "candidate_clips": [{"ref": c.ref, "scene_id": c.scene_id, "in": fmt_tc(c.start), "out": fmt_tc(c.end),
                                     "description": c.description} for c in self.candidates()]}

    # ---- planning -------------------------------------------------------
    def plan(self, aud: dict) -> dict:
        brief = self.build_brief(aud)
        self.log.record("strategy", f"Audience strategy for {aud['label']}: {aud['goal']} "
                        f"Usable insights: {[i['insight_id'] for i in brief['usable_insights']]}", aud["audience_id"])
        try:
            proposal, meta = self.router.call(f"propose_trailer:{aud['audience_id']}", self._proposal_payload(brief),
                                              audience=aud["audience_id"])
            source = {"proposal": "model", **meta}
        except ModelUnavailable as e:
            self.log.record("fallback", f"No model available ({e}); using deterministic planner", aud["audience_id"])
            proposal = self.deterministic_proposal(aud, brief)
            source = {"proposal": "deterministic", "model": "deterministic", "usd": 0.0}
        self.log.record("proposal", f"Promise: {proposal.get('audience_promise')}", aud["audience_id"],
                        segments=len(proposal.get("segments", [])), source=source["proposal"])
        return self.assemble(aud, proposal, source)

    def normalize_proposal(self, aud, proposal) -> dict:
        """Coerce the *shape* of a model proposal (never its choices) so malformed output can't crash the run.

        Real models return e.g. text cards as plain strings. Each coercion is logged; anything that can't be
        coerced is dropped and logged. Content is still judged only by the verifier.
        """
        notes = []
        acc = self.pkg.policies["accessibility"]

        def card(v, where):
            if isinstance(v, str):
                v = {"text": v}
                notes.append(f"{where}: text card given as a string")
            if not isinstance(v, dict) or not isinstance(v.get("text"), str) or not v["text"].strip():
                if v is not None:
                    notes.append(f"{where}: unusable text card dropped")
                return None
            secs = v.get("seconds")
            if not isinstance(secs, (int, float)) or secs <= 0:
                secs = round(max(acc["min_text_card_seconds"], len(v["text"]) / acc["text_card_cps"]) + 0.05, 1)
                notes.append(f"{where}: text card had no valid duration; set to readable minimum {secs}s")
            return {"text": v["text"], "seconds": float(secs)}

        p = dict(proposal)
        for key in ("objective", "audience_promise", "music_reason"):
            if not isinstance(p.get(key), str):
                p.pop(key, None)
        if isinstance(p.get("emotional_journey"), str):
            p["emotional_journey"] = [p["emotional_journey"]]
            notes.append("emotional_journey given as a string")
        p["emotional_journey"] = [str(x) for x in p.get("emotional_journey") or []]
        if not isinstance(p.get("music_bed"), str):
            p["music_bed"] = None
        p["insights_used"] = [i.get("insight_id") if isinstance(i, dict) else i
                              for i in p.get("insights_used") or [] if isinstance(i, (str, dict))]
        p["alternate_text_cards"] = [c for c in (card(c, "alternate_text_cards") for c in p.get("alternate_text_cards") or [])
                                     if c]
        segs = []
        for i, s in enumerate(p.get("segments") or [], start=1):
            if not isinstance(s, dict):
                notes.append(f"segment {i}: not an object, dropped")
                continue
            s = dict(s)
            if "text_card" in s:
                s["text_card"] = card(s["text_card"], f"segment {i}")
            vo = s.get("voice_over")
            if isinstance(vo, str):
                s["voice_over"] = {"text": vo}
                notes.append(f"segment {i}: voice_over given as a string")
            elif vo is not None and not (isinstance(vo, dict) and isinstance(vo.get("text"), str)):
                s["voice_over"] = None
                notes.append(f"segment {i}: unusable voice_over dropped")
            for k in ("video", "source_ref", "source_in", "source_out", "audio", "beat", "transition", "reason", "subtitle_track"):
                if k in s and s[k] is not None and not isinstance(s[k], str):
                    s[k] = str(s[k])
            segs.append(s)
        p["segments"] = segs
        for n in notes:
            self.log.record("model_output_normalized", n, aud["audience_id"])
        return p

    def assemble(self, aud, proposal, source) -> dict:
        proposal = self.normalize_proposal(aud, proposal)
        bed = proposal.get("music_bed")
        segments = [self.ground_segment(aud, spec, f"{aud['audience_id']}_s{i:02d}", i, bed)
                    for i, spec in enumerate(proposal.get("segments", []), start=1)]
        return {
            "trailer_id": f"{aud['audience_id']}_v1", "version": 1,
            "audience": aud["label"], "audience_id": aud["audience_id"], "market": aud["market"],
            "objective": proposal.get("objective", aud["goal"]),
            "audience_promise": proposal.get("audience_promise", ""),
            "emotional_journey": proposal.get("emotional_journey", []),
            "target_duration_seconds": aud["target_duration_seconds"],
            "duration_seconds": 0.0,
            "music_plan": {"bed_track": bed, "reason": proposal.get("music_reason", "")},
            "insights_used": list(proposal.get("insights_used", [])),
            "alternate_text_cards": proposal.get("alternate_text_cards", []),
            "segments": segments,
            "planning_source": source,
            "repair_history": [], "revisions": [],
        }

    def ground_segment(self, aud, spec, seg_id, order, bed) -> dict:
        audio = spec.get("audio", "dialogue_and_music")
        # Fill only what the proposal left out, from its own source_ref. Values the model did give are
        # kept as-is (even if wrong) so the verifier sees and reports the model's actual choice.
        video, tc_in, tc_out = spec.get("video"), spec.get("source_in"), spec.get("source_out")
        ref = self.pkg.resolve_ref(spec.get("source_ref"))
        if ref and ref["kind"] in ("line", "moment"):
            cand = next((c for c in self.candidates() if c.ref == spec["source_ref"]), None)
            video = video or ref["scene_id"]
            if not tc_in and not tc_out and cand:
                tc_in, tc_out = fmt_tc(cand.start), fmt_tc(cand.end)
        seg = {
            "segment_id": seg_id, "order": order, "beat": spec.get("beat", "beat"),
            "video": video, "source_ref": spec.get("source_ref"),
            "source_in": tc_in, "source_out": tc_out,
            "duration_seconds": None, "audio": audio,
            "music": bed if audio in MUSIC_AUDIO else None,
            "dialogue": [], "subtitle": None,
            "voice_over": spec.get("voice_over"), "text_card": spec.get("text_card"),
            "transition": spec.get("transition", "cut"), "reason": spec.get("reason", ""),
            "evidence": list(spec.get("evidence", [])), "depends_on": [], "risk_flags": [],
            "subtitle_track": spec.get("subtitle_track") or aud["subtitle_track"],
        }
        return self.reground(seg, aud)

    def reground(self, seg, aud) -> dict:
        """Re-derive every source-dependent field of a segment from the package."""
        pkg = self.pkg
        track = seg.pop("subtitle_track", None) or (seg.get("subtitle") or {}).get("track") or aud["subtitle_track"]
        scene = pkg.scene(seg.get("video"))
        try:
            t0, t1 = parse_tc(seg["source_in"]), parse_tc(seg["source_out"])
        except (TypeError, ValueError, KeyError):
            t0 = t1 = None
        seg["duration_seconds"] = round(t1 - t0, 3) if t0 is not None else None
        if seg.get("voice_over") and "caption" not in seg["voice_over"]:
            seg["voice_over"] = {**seg["voice_over"], "caption": seg["voice_over"].get("text")}
        deps = {f"policy:{aud['rating_policy']}", f"audience:{aud['audience_id']}", f"market:{aud['market']}"}
        evidence = [e for e in seg.get("evidence", []) if not e.startswith(("line:", "cue:", "contract:", "scene:", "moment:"))]
        if scene is None or t0 is None:
            seg.update(dialogue=[], subtitle=None, depends_on=sorted(deps | {f"scene:{seg.get('video')}"}),
                       evidence=evidence + [f"scene:{seg.get('video')}"])
            return seg
        lines = pkg.lines_in(scene, t0, t1)
        audible = seg["audio"] in AUDIBLE
        seg["dialogue"] = [{"line_id": l.line_id, "speaker": l.speaker, "text": l.text} for l in lines] if audible else []
        if audible and lines:
            cues = [{"line_id": l.line_id, "start": l.start, "end": l.end, "text": pkg.cue(track, l.line_id)} for l in lines]
            seg["subtitle"] = {"track": track, "text": " / ".join(c["text"] or "" for c in cues), "cues": cues}
            deps |= {f"cue:{track}:{l.line_id}" for l in lines}
        else:
            seg["subtitle"] = None
        if seg["audio"] in MUSIC_AUDIO:
            deps.add(f"music:{seg['music']}")
        if seg["audio"] == "original_mix" and scene.source_music:
            deps.add(f"music:{scene.source_music}")
        for ch in pkg.on_screen(scene, t0, t1) | ({l.speaker for l in lines} if audible else set()):
            actor = pkg.actor_for(ch)
            if actor:
                deps.add(f"actor:{actor['actor_id']}")
        deps |= {f"scene:{scene.scene_id}"} | {f"line:{l.line_id}" for l in lines}
        deps |= {f"moment:{m.moment_id}" for m in pkg.moments_in(scene, t0, t1)}
        seg["depends_on"] = sorted(deps)
        ev = [f"scene:{scene.scene_id}"]
        if seg.get("source_ref"):
            ev.append(seg["source_ref"])
        ev += [f"line:{l.line_id}" for l in lines if f"line:{l.line_id}" not in ev]
        ev += [f"cue:{track}:{l.line_id}" for l in lines] if seg["subtitle"] else []
        ev += [f"contract:{d.split(':', 1)[1]}" for d in sorted(deps) if d.startswith(("music:", "actor:"))]
        seg["evidence"] = list(dict.fromkeys(ev + evidence))
        return seg

    # ---- candidates, replacement, deterministic fallback -----------------
    def candidates(self) -> list[Candidate]:
        if hasattr(self, "_cands"):
            return self._cands
        pkg, tim = self.pkg, self.pkg.policies["timing"]
        sens = pkg.policies["sensitive_description_terms"]
        cands = []
        for s in pkg.episode.scenes:
            tags = frozenset(set(s.tags) | description_tags(s, sens))
            for l in s.dialogue:
                a = max(s.start_s, l.start_s - tim["line_pad_in_seconds"])
                b = min(s.end_s, l.end_s + tim["line_pad_out_seconds"])
                cands.append(Candidate(f"line:{l.line_id}", s.scene_id, a, b, "line", tags, f"'{l.text}' ({l.speaker})"))
            for m in s.moments:
                cands.append(Candidate(f"moment:{m.moment_id}", s.scene_id, m.start_s, m.end_s, "moment",
                                       tags | frozenset(m.visual_tags), m.description))
        self._cands = cands
        return cands

    def _score(self, c: Candidate, aud, beat_tags) -> float:
        prefer = {t for i in usable_insights(self.bias_review, aud["audience_id"]) for t in i["prefer_tags"]}
        caution = set(self.pkg.policies["rating_policies"][aud["rating_policy"]]["caution_tags"])
        scene = self.pkg.scene(c.scene_id)
        score = 3 * len(c.tags & set(beat_tags)) + len(c.tags & prefer) - 1.5 * len(c.tags & caution)
        score += self.pkg.historic.get("scene_scores", {}).get(c.scene_id, 0.0)
        if aud.get("dialect_audience") and ("dialect-rich" in c.tags or scene.cultural_notes):
            score += 2
        if c.kind == "line" and aud.get("dialect_audience"):
            score += 0.5
        return score

    def beat_tags(self, aud, beat) -> list[str]:
        for b in aud["beat_template"]:
            if b["beat"] == beat:
                return b["tags"]
        # A beat the audience template does not name (e.g. a model's "climax"): aim for the audience's overall tone.
        return sorted({t for b in aud["beat_template"] for t in b["tags"]})

    def find_replacement(self, plan, aud, index, beat, exclude_refs=()) -> tuple[dict | None, Candidate | None]:
        """Best candidate for a slot that passes every segment check and the neighbouring order checks."""
        segs = plan["segments"]
        old = segs[index] if index < len(segs) else None
        tags = self.beat_tags(aud, beat)
        elig = self.constraint_map["scene_eligibility"][aud["audience_id"]]
        used = {(s.get("video"), s.get("source_in"), s.get("source_out")) for i, s in enumerate(segs) if i != index}
        used_refs = {s.get("source_ref") for i, s in enumerate(segs) if i != index}
        spans = [(s.get("video"), *self.verifier.clip_bounds(s)[1:]) for i, s in enumerate(segs) if i != index]
        prev_seg = segs[index - 1] if index > 0 else None
        next_seg = segs[index + 1] if index + 1 < len(segs) else None
        ranked = sorted(self.candidates(), key=lambda c: (-self._score(c, aud, tags), c.ref))
        for c in ranked:
            if c.ref in exclude_refs or c.ref in used_refs or elig[c.scene_id]["status"] == "blocked":
                continue
            if any(v == c.scene_id and a is not None and a < c.end and c.start < b for v, a, b in spans):
                continue
            spec = {"beat": beat, "video": c.scene_id, "source_ref": c.ref, "source_in": fmt_tc(c.start),
                    "source_out": fmt_tc(c.end), "audio": "dialogue_and_music" if c.kind == "line" else "music_only",
                    "transition": old.get("transition", "cut") if old else "cut",
                    "reason": f"{c.description}. Best-scoring clip for the '{beat}' beat that passes every check "
                              f"(matches {sorted(c.tags & set(tags)) or 'audience tone'})."}
            seg = self.ground_segment(aud, spec, old["segment_id"] if old else "new", index + 1, plan["music_plan"]["bed_track"])
            if (seg["video"], seg["source_in"], seg["source_out"]) in used:
                continue
            if any(f["severity"] == "error" for f in self.verifier.check_segment(seg, aud)):
                continue
            if self.verifier.sequence_violations(prev_seg, seg) or self.verifier.sequence_violations(seg, next_seg):
                continue
            return seg, c
        return None, None

    def choose_music(self, aud, exclude=()) -> str | None:
        moods = aud["music_moods"]
        tracks = [t for t in self.pkg.usable_tracks(aud["market"]) if t not in exclude]
        tracks.sort(key=lambda t: (-len(set(self.pkg.music[t]["moods"]) & set(moods)), t))
        return tracks[0] if tracks else None

    def deterministic_proposal(self, aud, brief) -> dict:
        """Template planner used when no model is available (and as the zero-cost fallback plan)."""
        bed = self.choose_music(aud)
        plan = {"segments": [], "music_plan": {"bed_track": bed}}
        chosen = []
        for i, b in enumerate(aud["beat_template"]):
            plan["segments"].append({"segment_id": f"slot{i}", "video": None})
            seg, cand = self.find_replacement(plan, aud, i, b["beat"])
            if seg is None:
                plan["segments"].pop()
                continue
            plan["segments"][-1] = seg
            chosen.append({"beat": b["beat"], "source_ref": seg["source_ref"], "video": seg["video"],
                           "source_in": seg["source_in"], "source_out": seg["source_out"], "audio": seg["audio"],
                           "transition": "cut", "reason": f"Template beat '{b['beat']}' matched by tags: {cand.description}"})
        return {"objective": aud["goal"], "audience_promise": aud["fallback_promise"],
                "emotional_journey": aud["fallback_journey"], "music_bed": bed,
                "music_reason": f"Highest mood match among tracks cleared for {aud['market']}",
                "insights_used": [i["insight_id"] for i in brief["usable_insights"]],
                "alternate_text_cards": [], "segments": chosen}
