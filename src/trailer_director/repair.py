"""Repair step: act on verifier findings with the smallest change that fixes them.

Order of preference per segment: fix in place (swap music, use the dialogue stem,
switch subtitle track, fix a text card) -> trim the offending range out of the
clip -> replace the clip with the best candidate that passes every check -> drop
the segment. Nothing here bypasses the verifier: every candidate change is
re-checked, and whatever cannot be fixed stays in the plan as an error.
"""
import copy

from .timecode import fmt_tc

TEXT_FIXES = ("remove_text_card", "extend_card", "remove_voice_over", "add_caption")


def _summary(seg):
    return {"video": seg.get("video"), "source_ref": seg.get("source_ref"), "source_in": seg.get("source_in"),
            "source_out": seg.get("source_out"), "audio": seg.get("audio"), "music": seg.get("music"),
            "subtitle_track": (seg.get("subtitle") or {}).get("track"),
            "text_card": (seg.get("text_card") or {}).get("text")}


class Repairer:
    def __init__(self, pkg, planner, verifier, log):
        self.pkg = pkg
        self.planner = planner
        self.verifier = verifier
        self.log = log

    def repair(self, plan: dict, aud: dict, result: dict, round_no: int) -> list[dict]:
        self._actions = []
        self._round = round_no
        self._plan, self._aud = plan, aud
        errors = result["errors"]

        for f in [e for e in errors if e["segment_id"] is None]:
            if f.get("fix") == "swap_music":
                self._swap_bed(f)
            elif f.get("fix") == "drop_insight":
                ins = f["refs"][0]
                if ins in plan["insights_used"]:
                    plan["insights_used"].remove(ins)
                    self._act("drop_insight", None, because=[f"{f['check_id']}: {f['message']}"], insight=ins)

        by_seg = {}
        for f in errors:
            if f["segment_id"]:
                by_seg.setdefault(f["segment_id"], []).append(f)
        for seg_id, fs in by_seg.items():
            idx = self._index(seg_id)
            if idx is not None:
                self._repair_segment(idx, fs)

        if any(f.get("fix") == "adjust_duration" for f in errors):
            self._adjust_duration()
        for i, s in enumerate(plan["segments"], start=1):
            s["order"] = i
        return self._actions

    # ---- helpers ---------------------------------------------------------
    def _index(self, seg_id):
        return next((i for i, s in enumerate(self._plan["segments"]) if s["segment_id"] == seg_id), None)

    def _act(self, action, seg_id, because, **details):
        entry = {"round": self._round, "action": action, "segment_id": seg_id, "because": because, **details}
        self._actions.append(entry)
        self.log.record("repair", f"{action} on {seg_id or 'plan'}", self._aud["audience_id"], **{k: v for k, v in entry.items() if k != "round"}, round=self._round)

    def _errors(self, seg, only=None):
        errs = [f for f in self.verifier.check_segment(seg, self._aud) if f["severity"] == "error"]
        return [f for f in errs if f["check_id"] in only] if only else errs

    def _reasons(self, fs):
        return [f"{f['check_id']}: {f['message']}" for f in fs]

    # ---- plan-level ------------------------------------------------------
    def _swap_bed(self, f):
        plan, aud = self._plan, self._aud
        old = plan["music_plan"]["bed_track"]
        new = self.planner.choose_music(aud, exclude={old})
        if new is None:
            self._act("swap_music_failed", None, because=[f["message"]], note="no cleared track available for this market")
            return
        matched = sorted(set(self.pkg.music[new]["moods"]) & set(aud["music_moods"]))
        fit = (f"matches moods {matched}" if matched else
               f"is the closest cleared option but matches none of {aud['music_moods']}; editor should choose the final track")
        plan["music_plan"] = {"bed_track": new, "reason": f"Replaced {old}: {f['message']}. {new} is cleared for "
                              f"{aud['market']} through the campaign window and {fit}."}
        for s in plan["segments"]:
            if s.get("music") == old or (s.get("music") is None and s.get("audio") in ("dialogue_and_music", "music_only")):
                s["music"] = new
                self.planner.reground(s, aud)
        self._act("swap_music", None, because=[f["message"]], **{"from": old, "to": new})

    # ---- segment-level ---------------------------------------------------
    def _repair_segment(self, idx, fs):
        plan, aud = self._plan, self._aud
        seg = plan["segments"][idx]
        fixes = {f.get("fix") for f in fs}
        if "replace_clip" in fixes:
            return self._replace(idx, fs)
        if "trim" in fixes:
            if not self._trim(idx, fs):
                self._replace(idx, fs)
            return
        if "mute_dialogue" in fixes:
            muted = {r for f in fs if f.get("fix") == "mute_dialogue" for r in f.get("refs", [])}
            if seg.get("source_ref") in muted:
                return self._replace(idx, fs)
            before = _summary(seg)
            seg.update(audio="music_only", music=plan["music_plan"]["bed_track"])
            self.planner.reground(seg, aud)
            self._act("mute_dialogue", seg["segment_id"], self._reasons([f for f in fs if f.get("fix") == "mute_dialogue"]),
                      **{"from": before, "to": _summary(seg)})
        if "use_dialogue_stem" in fixes:
            before = _summary(seg)
            seg.update(audio="dialogue_and_music", music=plan["music_plan"]["bed_track"])
            self.planner.reground(seg, aud)
            self._act("use_dialogue_stem", seg["segment_id"],
                      self._reasons([f for f in fs if f.get("fix") == "use_dialogue_stem"]), **{"from": before, "to": _summary(seg)})
        if "swap_music" in fixes and seg.get("music") != plan["music_plan"]["bed_track"]:
            before = _summary(seg)
            seg["music"] = plan["music_plan"]["bed_track"]
            self.planner.reground(seg, aud)
            self._act("swap_music", seg["segment_id"], self._reasons(fs), **{"from": before, "to": _summary(seg)})
        if "switch_subtitle_track" in fixes:
            if not self._switch_track(idx, [f for f in fs if f.get("fix") == "switch_subtitle_track"]):
                return self._replace(idx, fs)
        if "reground" in fixes:
            self.planner.reground(seg, aud)
            self._act("reground", seg["segment_id"], self._reasons([f for f in fs if f.get("fix") == "reground"]))
        if fixes & set(TEXT_FIXES):
            self._fix_text(plan["segments"][idx], [f for f in fs if f.get("fix") in TEXT_FIXES])

    def _replace(self, idx, fs):
        plan, aud = self._plan, self._aud
        old = plan["segments"][idx]
        new, cand = self.planner.find_replacement(plan, aud, idx, old["beat"], exclude_refs={old.get("source_ref")})
        reasons = self._reasons(fs)
        self._note_rejected_idea(old, fs)
        if new is None:
            plan["segments"].pop(idx)
            self._act("drop_segment", old["segment_id"], reasons, note="no candidate for this beat passes all checks",
                      **{"from": _summary(old)})
            return
        text_bad = any(f.get("fix") in TEXT_FIXES for f in fs)
        if old.get("text_card") and not text_bad:
            new["text_card"] = old["text_card"]
        if old.get("voice_over") and not text_bad:
            new["voice_over"] = old["voice_over"]
        plan["segments"][idx] = new
        self._act("replace_clip", old["segment_id"], reasons, **{"from": _summary(old), "to": _summary(new)},
                  replacement_reason=new["reason"])
        if old.get("text_card") and text_bad:
            self._fix_text(new, [f for f in fs if f.get("fix") in TEXT_FIXES])

    def _note_rejected_idea(self, old, fs):
        scores = self.pkg.historic.get("scene_scores", {})
        checks = {f["check_id"] for f in fs}
        if "SRC-001" in checks:
            self.log.record("hallucination_rejected", f"Model proposed nonexistent scene '{old.get('video')}' "
                            f"(\"{old.get('reason')}\"); verifier rejected it", self._aud["audience_id"], segment_id=old["segment_id"])
        if scores and old.get("video") == max(scores, key=scores.get) and checks & {"SPL-001", "SPL-002", "SPL-003"}:
            self.log.record("high_performing_idea_rejected",
                            f"{old['video']} has the highest historic engagement score ({scores[old['video']]}) but reveals a "
                            "protected story fact; engagement never overrides the spoiler policy",
                            self._aud["audience_id"], segment_id=old["segment_id"])

    def _trim(self, idx, fs) -> bool:
        plan, aud = self._plan, self._aud
        seg = plan["segments"][idx]
        scene, t0, t1 = self.verifier.clip_bounds(seg)
        bad = sorted(tuple(f["offending_range"]) for f in fs if f.get("offending_range"))
        pieces, cur = [], t0
        for a, b in bad:
            if a > cur:
                pieces.append((cur, min(a, t1)))
            cur = max(cur, b)
        if cur < t1:
            pieces.append((cur, t1))
        tim = self.pkg.policies["timing"]
        pieces = [(a, min(b, a + tim["max_clip_seconds"])) for a, b in pieces if b - a >= tim["min_clip_seconds"]]
        if not pieces:
            return False
        a, b = max(pieces, key=lambda p: p[1] - p[0])
        trial = copy.deepcopy(seg)
        trial.update(source_in=fmt_tc(a), source_out=fmt_tc(b))
        inside = [f"moment:{m.moment_id}" for m in self.pkg.moments_in(scene, a, b) if a <= m.start_s and m.end_s <= b]
        inside += [f"line:{l.line_id}" for l in self.pkg.lines_in(scene, a, b) if a <= l.start_s and l.end_s <= b]
        if trial.get("source_ref") not in inside:
            trial["source_ref"] = inside[0] if inside else None
        trial["subtitle_track"] = (seg.get("subtitle") or {}).get("track")
        self.planner.reground(trial, aud)
        if self._errors(trial):
            return False
        plan["segments"][idx] = trial
        self._act("trim", seg["segment_id"], self._reasons(fs), **{"from": _summary(seg), "to": _summary(trial)})
        return True

    def _switch_track(self, idx, fs) -> bool:
        plan, aud = self._plan, self._aud
        seg = plan["segments"][idx]
        current = (seg.get("subtitle") or {}).get("track")
        order = [aud["subtitle_track"]] + sorted(t for t in self.pkg.subtitles["tracks"] if t != aud["subtitle_track"])
        for t in order:
            if t == current:
                continue
            trial = copy.deepcopy(seg)
            trial["subtitle_track"] = t
            self.planner.reground(trial, aud)
            if not self._errors(trial, only={"TRU-002", "DIA-001", "SRC-006"}):
                plan["segments"][idx] = trial
                self._act("switch_subtitle_track", seg["segment_id"], self._reasons(fs), **{"from": current, "to": t})
                return True
        return False

    def _fix_text(self, seg, fs):
        plan, aud = self._plan, self._aud
        fixes = {f.get("fix") for f in fs}
        acc = self.pkg.policies["accessibility"]
        if "extend_card" in fixes and seg.get("text_card") and "remove_text_card" not in fixes:
            card = seg["text_card"]
            need = round(max(acc["min_text_card_seconds"], len(card["text"]) / acc["text_card_cps"]) + 0.05, 1)
            if need <= (seg.get("duration_seconds") or 0):
                before = card["seconds"]
                seg["text_card"] = {**card, "seconds": need}
                self._act("extend_card", seg["segment_id"], self._reasons(fs), **{"from": before, "to": need})
            else:
                fixes.add("remove_text_card")
        if "remove_text_card" in fixes and seg.get("text_card"):
            old = seg["text_card"]
            seg["text_card"] = None
            chosen = None
            for alt in list(plan.get("alternate_text_cards", [])):
                need = max(acc["min_text_card_seconds"], len(alt["text"]) / acc["text_card_cps"])
                trial = {**seg, "text_card": {"text": alt["text"], "seconds": round(max(alt.get("seconds", 0), need) + 0.05, 1)}}
                if not self._errors(trial, only={"DIA-002", "RAT-003", "SPL-002", "TRU-001", "ACC-003"}):
                    chosen = trial["text_card"]
                    plan["alternate_text_cards"].remove(alt)
                    break
            seg["text_card"] = chosen
            self._act("replace_text_card" if chosen else "remove_text_card", seg["segment_id"], self._reasons(fs),
                      **{"from": old["text"], "to": chosen["text"] if chosen else None})
        if "remove_voice_over" in fixes and seg.get("voice_over"):
            old = seg["voice_over"]["text"]
            seg["voice_over"] = None
            self._act("remove_voice_over", seg["segment_id"], self._reasons(fs), **{"from": old})
        if "add_caption" in fixes and seg.get("voice_over"):
            seg["voice_over"] = {**seg["voice_over"], "caption": seg["voice_over"]["text"]}
            self._act("add_caption", seg["segment_id"], self._reasons(fs))

    def _adjust_duration(self):
        plan, aud = self._plan, self._aud
        lo, hi = aud["target_duration_seconds"]
        total = lambda: sum(s.get("duration_seconds") or 0 for s in plan["segments"])
        before = round(total(), 3)
        used_beats = [s["beat"] for s in plan["segments"]]
        template = [b["beat"] for b in aud["beat_template"]]
        middle_beats = template[1:-1] or template  # never add a second hook or button
        for _ in range(8):
            if total() >= lo:
                break
            beat = min(middle_beats, key=lambda b: (used_beats.count(b), middle_beats.index(b)))
            pos = max(len(plan["segments"]) - 1, 0)
            n = max([int(s["segment_id"].rsplit("_s", 1)[-1]) for s in plan["segments"] if "_s" in s["segment_id"]] + [0]) + 1
            plan["segments"].insert(pos, {"segment_id": f"{aud['audience_id']}_s{n:02d}", "beat": beat, "video": None,
                                          "transition": "cut"})
            seg, _ = self.planner.find_replacement(plan, aud, pos, beat)
            if seg is None:
                plan["segments"].pop(pos)
                break
            plan["segments"][pos] = seg
            used_beats.append(beat)
            self._act("add_segment", seg["segment_id"], [f"TIM-001: total {before}s below {lo}s"], to=_summary(seg))
        while total() > hi and len(plan["segments"]) > 2:
            middle = plan["segments"][1:-1]
            excess = total() - hi
            victim = min(middle, key=lambda s: (abs((s.get("duration_seconds") or 0) - excess), s["segment_id"]))
            plan["segments"].remove(victim)
            self._act("drop_segment", victim["segment_id"], [f"TIM-001: total {before}s above {hi}s"], **{"from": _summary(victim)})
