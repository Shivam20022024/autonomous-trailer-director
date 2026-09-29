"""Deterministic verifier.

Reads only the edit decision list and the authoritative inputs (episode package,
subtitles, policies, contracts, audience definitions) plus the evidence-checked
story and spoiler maps. It never sees the planner's reasoning or prompts.

Every finding is structured: check id, severity, segment, message and a fix
category the repair step can act on.
"""
from .bias import review_insights
from .text_rules import description_tags, find_terms, has_term, vocative_kinship_terms
from .timecode import overlaps, parse_tc

ERROR, WARNING = "error", "warning"

CHECKS = {
    "AUD-001": "audience definition exists",
    "SRC-001": "scene exists in episode",
    "SRC-002": "timecodes valid and inside the scene",
    "SRC-003": "source reference exists and is inside the clip",
    "SRC-004": "quoted dialogue exists, is verbatim and is inside the clip",
    "SRC-005": "evidence references exist",
    "SRC-006": "subtitle text matches the named subtitle track",
    "SPL-001": "clip does not show a protected story fact",
    "SPL-002": "text card / voice-over / subtitles do not state a protected fact",
    "SPL-003": "clip order does not imply a protected fact",
    "SPL-004": "spoiler coverage is complete (verified story analysis available)",
    "RAT-001": "no forbidden content for the audience rating",
    "RAT-002": "caution content flagged for standards review",
    "RAT-003": "text card / voice-over wording allowed for the audience",
    "RGT-001": "music cleared for promos, market and campaign window",
    "RGT-002": "on-screen actors cleared for promo video in the market",
    "RGT-003": "audible voices cleared for promo use",
    "RGT-004": "minors on screen flagged for legal sign-off",
    "TRU-001": "text card / voice-over claims supported by the episode",
    "TRU-002": "subtitles preserve story-map relationships",
    "TRU-003": "trailer intensity not misleading relative to the episode",
    "ACC-001": "audible dialogue is subtitled",
    "ACC-002": "subtitle reading speed within limit",
    "ACC-003": "text cards on screen long enough to read",
    "ACC-004": "voice-over is captioned",
    "DIA-001": "dialect audience gets its dialect subtitle track",
    "DIA-002": "no stereotyping language",
    "DIA-003": "dialect not used mainly as a comic device",
    "DIA-004": "dialect trailer shows language or cultural context",
    "PER-001": "only bias-reviewed audience insights used",
    "TIM-001": "total duration within target",
    "TIM-002": "clip length within limits",
    "TIM-003": "no duplicate or overlapping clips",
    "TIM-004": "clips do not cut dialogue mid-line",
    "CRE-001": "plan has a promise and a multi-beat structure",
    "CRE-002": "music bed matches the audience's intended mood",
    "SEC-001": "source text with instruction-like content flagged",
    "DESC-001": "human/AI description mismatch flagged",
    "BUD-001": "planning stayed within budget",
}


def finding(check, severity, segment_id, message, fix=None, refs=None, rng=None, approval=None):
    f = {"check_id": check, "severity": severity, "segment_id": segment_id, "message": message}
    if fix:
        f["fix"] = fix
    if refs:
        f["refs"] = refs
    if rng:
        f["offending_range"] = list(rng)
    if approval:
        f["approval"] = approval
    return f


class Verifier:
    def __init__(self, pkg, story_map: dict, spoiler_map: dict):
        self.pkg = pkg
        self.pol = pkg.policies
        self.relations = {(r["from"], r["to"]): r["relation"] for r in story_map["relationships"]}
        self.flagged_scenes = {f["scene_id"] for f in story_map["untrusted_text_flags"] if f.get("scene_id")}
        self.mismatch_scenes = {}
        for m in story_map["description_mismatches"]:
            self.mismatch_scenes.setdefault(m["scene_id"], []).append(m["term"])
        self.protected = [(f, r, parse_tc(r["start"]), parse_tc(r["end"]))
                          for f in spoiler_map["protected_facts"] for r in f["protected_ranges"]]
        self.fact_keywords = [(f["fact_id"], kw) for f in spoiler_map["protected_facts"] for kw in f["text_keywords"]]
        self.sequences = [(f["fact_id"], a, b) for f in spoiler_map["protected_facts"] for a, b in f["forbidden_sequences"]]
        self.spoiler_coverage = spoiler_map.get("coverage", "editorial_only")
        self.insight_review = review_insights(pkg)
        corpus = [s.human_description for s in pkg.episode.scenes] + [l.text for _, l in pkg.lines.values()]
        self.episode_text = " ".join(corpus)

    # ---- plan -----------------------------------------------------------
    def verify_plan(self, plan: dict) -> dict:
        aud = self.pkg.audience(plan.get("audience_id"))
        if aud is None:
            return self._summary([finding("AUD-001", ERROR, None, f"Unknown audience '{plan.get('audience_id')}'")])
        findings = []
        for seg in plan.get("segments", []):
            findings += self.check_segment(seg, aud)
        findings += self.check_plan(plan, aud)
        return self._summary(findings)

    def _summary(self, findings):
        errors = [f for f in findings if f["severity"] == ERROR]
        warnings = [f for f in findings if f["severity"] == WARNING]
        status = "FAIL" if errors else "PASS_WITH_WARNINGS" if warnings else "PASS"
        return {"status": status, "errors": errors, "warnings": warnings, "checks_run": sorted(CHECKS)}

    # ---- segment --------------------------------------------------------
    def clip_bounds(self, seg):
        scene = self.pkg.scene(seg.get("video"))
        try:
            t0, t1 = parse_tc(seg.get("source_in")), parse_tc(seg.get("source_out"))
        except (TypeError, ValueError):
            return scene, None, None
        return scene, t0, t1

    def check_segment(self, seg: dict, aud: dict) -> list[dict]:
        pkg, pol = self.pkg, self.pol
        sid = seg.get("segment_id")
        scene = pkg.scene(seg.get("video"))
        if scene is None:
            return [finding("SRC-001", ERROR, sid, f"Scene '{seg.get('video')}' does not exist in episode "
                            f"{pkg.episode.episode_id}; the clip cannot be sourced", fix="replace_clip")]
        _, t0, t1 = self.clip_bounds(seg)
        if t0 is None:
            return [finding("SRC-002", ERROR, sid, f"Malformed timecodes {seg.get('source_in')!r}-{seg.get('source_out')!r}",
                            fix="replace_clip")]
        if not (scene.start_s <= t0 < t1 <= scene.end_s):
            return [finding("SRC-002", ERROR, sid, f"{seg['source_in']}-{seg['source_out']} is outside {scene.scene_id} "
                            f"({scene.start_time}-{scene.end_time}) or reversed", fix="replace_clip")]
        out = []
        ref = seg.get("source_ref")
        if ref:
            r = pkg.resolve_ref(ref)
            if r is None or r["scene_id"] != scene.scene_id:
                out.append(finding("SRC-003", ERROR, sid, f"Source reference '{ref}' does not exist in {scene.scene_id}", fix="replace_clip"))
            elif not overlaps(r["start"], r["end"], t0, t1):
                out.append(finding("SRC-003", ERROR, sid, f"Clip does not contain its source reference '{ref}'", fix="replace_clip"))

        tim = pol["timing"]
        dur = t1 - t0
        if dur < tim["min_clip_seconds"]:
            out.append(finding("TIM-002", ERROR, sid, f"Clip is {dur:.2f}s, under {tim['min_clip_seconds']}s", fix="replace_clip"))
        elif dur > tim["max_clip_seconds"]:
            out.append(finding("TIM-002", ERROR, sid, f"Clip is {dur:.2f}s, over {tim['max_clip_seconds']}s", fix="trim",
                               rng=(t0 + tim["max_clip_seconds"], t1)))

        audio = seg.get("audio")
        audible = audio in ("original_mix", "dialogue_and_music", "dialogue_only")
        lines = pkg.lines_in(scene, t0, t1)
        out += self._dialogue_and_subtitles(seg, aud, scene, lines, audible, t0, t1)
        out += self._spoilers(seg, scene, t0, t1)
        out += self._rating(seg, aud, scene, t0, t1)
        out += self._rights(seg, aud, scene, lines, audible, t0, t1)
        out += self._overlay_text(seg, aud, dur)

        if scene.scene_id in self.flagged_scenes:
            out.append(finding("SEC-001", WARNING, sid, f"{scene.scene_id} metadata contains instruction-like text; it was "
                               "ignored, but the source metadata should be reviewed", approval="security/metadata review"))
        if scene.scene_id in self.mismatch_scenes:
            out.append(finding("DESC-001", WARNING, sid, f"Human and AI descriptions of {scene.scene_id} disagree on "
                               f"{self.mismatch_scenes[scene.scene_id]}; verify the footage", approval="editorial: verify footage"))
        for ev in seg.get("evidence", []):
            if not pkg.ref_exists(ev):
                out.append(finding("SRC-005", ERROR, sid, f"Evidence reference '{ev}' does not exist", fix="reground"))
        return out

    def _dialogue_and_subtitles(self, seg, aud, scene, lines, audible, t0, t1):
        pkg, sid = self.pkg, seg.get("segment_id")
        out = []
        listed = {d.get("line_id"): d for d in seg.get("dialogue", [])}
        in_clip = {l.line_id: l for l in lines}
        for lid, d in listed.items():
            if lid not in in_clip:
                out.append(finding("SRC-004", ERROR, sid, f"Quoted line '{lid}' is not in this clip", fix="reground"))
            elif d.get("text") != in_clip[lid].text:
                out.append(finding("SRC-004", ERROR, sid, f"Line '{lid}' is misquoted", fix="reground"))
        if not audible:
            return out
        for l in lines:
            if l.line_id not in listed:
                out.append(finding("SRC-004", ERROR, sid, f"Audible line '{l.line_id}' is not listed in the EDL", fix="reground"))
            if l.start_s < t0 or l.end_s > t1:
                out.append(finding("TIM-004", WARNING, sid, f"Clip cuts line '{l.line_id}' mid-delivery"))
        if not lines:
            return out
        sub = seg.get("subtitle")
        if not sub:
            return out + [finding("ACC-001", ERROR, sid, "Audible dialogue has no subtitles", fix="reground")]
        track = sub.get("track")
        if track not in pkg.subtitles["tracks"]:
            return out + [finding("SRC-006", ERROR, sid, f"Subtitle track '{track}' does not exist", fix="switch_subtitle_track")]
        if aud.get("dialect_audience") and track != aud["subtitle_track"]:
            out.append(finding("DIA-001", ERROR, sid, f"Dialect audience needs '{aud['subtitle_track']}' subtitles, got '{track}'",
                               fix="switch_subtitle_track"))
        cues = {c.get("line_id"): c for c in sub.get("cues", [])}
        max_cps = self.pol["accessibility"]["max_subtitle_cps"]
        for l in lines:
            expected = pkg.cue(track, l.line_id)
            got = cues.get(l.line_id, {}).get("text")
            if expected is None or got != expected:
                out.append(finding("SRC-006", ERROR, sid, f"Subtitle for '{l.line_id}' does not match track '{track}'", fix="reground"))
                continue
            cps = len(expected) / (l.end_s - l.start_s)
            if cps > max_cps:
                out.append(finding("ACC-002", WARNING, sid, f"Subtitle '{l.line_id}' needs {cps:.1f} chars/s (limit {max_cps})",
                                   approval="accessibility: condense subtitle"))
            for term in vocative_kinship_terms(expected, self.pol["kinship_lexicon"]):
                rel = self.relations.get((l.speaker, l.addressee))
                allowed = self.pol["kinship_lexicon"][term]
                if rel is None:
                    out.append(finding("TRU-002", WARNING, sid, f"'{term}' in {track}:{l.line_id} implies a relationship the "
                                       "story map cannot confirm", approval="cultural reviewer: check form of address"))
                elif rel not in allowed:
                    out.append(finding("TRU-002", ERROR, sid, f"Subtitle {track}:{l.line_id} addresses {l.addressee} as '{term}' "
                                       f"({'/'.join(allowed)}), but the story map says {l.addressee} is {l.speaker}'s {rel}",
                                       fix="switch_subtitle_track", refs=[f"cue:{track}:{l.line_id}"]))
        return out

    def _spoilers(self, seg, scene, t0, t1):
        out = []
        for fact, r, rs, re in self.protected:
            if r["scene_id"] == scene.scene_id and overlaps(rs, re, t0, t1):
                inner = not r["ref"].startswith("scene:")
                out.append(finding("SPL-001", ERROR, seg.get("segment_id"),
                                   f"Clip shows protected fact {fact['fact_id']} ({fact['statement']}) via {r['ref']}",
                                   fix="trim" if inner else "replace_clip", refs=[r["ref"]], rng=(rs, re)))
        return out

    def _rating(self, seg, aud, scene, t0, t1):
        pol = self.pol["rating_policies"][aud["rating_policy"]]
        sid, out = seg.get("segment_id"), []
        tags = set(scene.tags) | description_tags(scene, self.pol["sensitive_description_terms"])
        for tag in sorted(tags & set(pol["forbidden_tags"])):
            out.append(finding("RAT-001", ERROR, sid, f"{scene.scene_id} carries '{tag}', forbidden for {aud['label']}",
                               fix="replace_clip"))
        for tag in sorted(tags & set(pol["caution_tags"])):
            out.append(finding("RAT-002", WARNING, sid, f"{scene.scene_id} carries '{tag}'; needs standards review for {aud['label']}",
                               approval="standards review"))
        for m in self.pkg.moments_in(scene, t0, t1):
            for vt in sorted(set(m.visual_tags) & set(pol["forbidden_visual_tags"])):
                out.append(finding("RAT-001", ERROR, sid, f"Shot {m.moment_id} contains '{vt}', forbidden for {aud['label']}",
                                   fix="trim", refs=[f"moment:{m.moment_id}"], rng=(m.start_s, m.end_s)))
        return out

    def _rights(self, seg, aud, scene, lines, audible, t0, t1):
        pkg, sid, market, out = self.pkg, seg.get("segment_id"), aud["market"], []
        for ch in sorted(pkg.on_screen(scene, t0, t1)):
            actor = pkg.actor_for(ch)
            if actor is None:
                out.append(finding("RGT-002", ERROR, sid, f"No actor contract for on-screen character '{ch}'", fix="replace_clip"))
                continue
            if not actor["promo_video"]:
                out.append(finding("RGT-002", ERROR, sid, f"{ch} ({actor['actor_id']}) is not cleared to appear in promos",
                                   fix="replace_clip", refs=[f"contract:{actor['actor_id']}"]))
            if market not in actor["territories"]:
                out.append(finding("RGT-002", ERROR, sid, f"{ch} ({actor['actor_id']}) is not cleared in market '{market}'",
                                   fix="replace_clip", refs=[f"contract:{actor['actor_id']}"]))
            if actor.get("minor"):
                out.append(finding("RGT-004", WARNING, sid, f"{ch} is a minor; promo use needs legal sign-off",
                                   approval="legal: minor in promo"))
        if audible:
            for l in lines:
                actor = pkg.actor_for(l.speaker)
                if actor and not actor["promo_voice"]:
                    out.append(finding("RGT-003", ERROR, sid, f"{l.speaker}'s voice ({actor['actor_id']}) is not cleared for promos "
                                       f"(line {l.line_id})", fix="mute_dialogue", refs=[f"line:{l.line_id}"],
                                       rng=(l.start_s, l.end_s)))
        audio = seg.get("audio")
        if audio in ("dialogue_and_music", "music_only"):
            track = seg.get("music")
            if not track:
                out.append(finding("RGT-001", ERROR, sid, "Segment needs a music track but none is set", fix="swap_music"))
            else:
                for p in pkg.music_problems(track, market):
                    out.append(finding("RGT-001", ERROR, sid, p, fix="swap_music", refs=[f"contract:{track}"]))
        if audio == "original_mix" and scene.source_music:
            for p in pkg.music_problems(scene.source_music, market):
                out.append(finding("RGT-001", ERROR, sid, f"Original mix of {scene.scene_id} carries source music: {p}",
                                   fix="use_dialogue_stem", refs=[f"contract:{scene.source_music}"]))
        return out

    def _overlay_text(self, seg, aud, dur):
        pol = self.pol
        rating = pol["rating_policies"][aud["rating_policy"]]
        sid, out = seg.get("segment_id"), []
        items = []
        if seg.get("text_card"):
            items.append(("text_card", seg["text_card"].get("text", ""), "remove_text_card"))
        if seg.get("voice_over"):
            items.append(("voice_over", seg["voice_over"].get("text", ""), "remove_voice_over"))
        for kind, text, fix in items:
            for t in find_terms(text, pol["stereotype_lexicon"]):
                out.append(finding("DIA-002", ERROR, sid, f"{kind} '{text}' uses stereotyping language ('{t}')", fix=fix))
            for w in find_terms(text, rating["forbidden_words"]):
                out.append(finding("RAT-003", ERROR, sid, f"{kind} '{text}' uses '{w}', not allowed for {aud['label']}", fix=fix))
            for fact_id, kw in self.fact_keywords:
                if has_term(text, kw):
                    out.append(finding("SPL-002", ERROR, sid, f"{kind} '{text}' states protected fact {fact_id} ('{kw}')", fix=fix))
            for claim, support in pol["claim_lexicon"].items():
                if has_term(text, claim) and not find_terms(self.episode_text, support):
                    out.append(finding("TRU-001", ERROR, sid, f"{kind} '{text}' claims '{claim}', which nothing in the "
                                       "episode supports (misleading)", fix=fix))
        card = seg.get("text_card")
        if card:
            acc = pol["accessibility"]
            need = max(acc["min_text_card_seconds"], len(card.get("text", "")) / acc["text_card_cps"])
            if card.get("seconds", 0) + 1e-9 < need:
                out.append(finding("ACC-003", ERROR, sid, f"Text card needs {need:.2f}s to read, has {card.get('seconds')}s",
                                   fix="extend_card"))
            elif card.get("seconds", 0) > dur + 1e-9:
                out.append(finding("ACC-003", ERROR, sid, f"Text card ({card['seconds']}s) outlasts its clip ({dur:.2f}s)",
                                   fix="remove_text_card"))
        vo = seg.get("voice_over")
        if vo and pol["accessibility"]["require_captions_for_voice_over"] and vo.get("caption") != vo.get("text"):
            out.append(finding("ACC-004", ERROR, sid, "Voice-over is not captioned verbatim", fix="add_caption"))
        return out

    # ---- plan-level -----------------------------------------------------
    def refs_covered(self, seg) -> set[str]:
        scene, t0, t1 = self.clip_bounds(seg)
        if scene is None or t0 is None:
            return set()
        refs = {f"scene:{scene.scene_id}"}
        refs |= {f"line:{l.line_id}" for l in self.pkg.lines_in(scene, t0, t1)}
        refs |= {f"moment:{m.moment_id}" for m in self.pkg.moments_in(scene, t0, t1)}
        return refs

    def sequence_violations(self, first, second) -> list[tuple[str, str, str]]:
        if not first or not second:
            return []
        a_refs, b_refs = self.refs_covered(first), self.refs_covered(second)
        return [(fid, a, b) for fid, a, b in self.sequences if a in a_refs and b in b_refs]

    def check_plan(self, plan, aud) -> list[dict]:
        pkg, out = self.pkg, []
        segs = plan.get("segments", [])
        durations = []
        for s in segs:
            _, t0, t1 = self.clip_bounds(s)
            durations.append(t1 - t0 if t0 is not None else 0.0)
        total = sum(durations)
        lo, hi = aud["target_duration_seconds"]
        if not lo <= total <= hi:
            out.append(finding("TIM-001", ERROR, None, f"Total duration {total:.2f}s is outside {lo}-{hi}s", fix="adjust_duration"))

        seen = []
        for s in segs:
            scene, t0, t1 = self.clip_bounds(s)
            if scene is None or t0 is None:
                continue
            for other_id, sc, a0, a1 in seen:
                if sc == scene.scene_id and overlaps(a0, a1, t0, t1):
                    out.append(finding("TIM-003", ERROR, s["segment_id"], f"Clip overlaps {other_id}", fix="replace_clip"))
                    break
            seen.append((s["segment_id"], scene.scene_id, t0, t1))

        for a, b in zip(segs, segs[1:]):
            for fid, ra, rb in self.sequence_violations(a, b):
                out.append(finding("SPL-003", ERROR, b["segment_id"], f"Cutting from {ra} to {rb} implies protected fact {fid}",
                                   fix="replace_clip", refs=[ra, rb]))

        track = (plan.get("music_plan") or {}).get("bed_track")
        if track:
            for p in pkg.music_problems(track, aud["market"]):
                out.append(finding("RGT-001", ERROR, None, f"Music bed: {p}", fix="swap_music", refs=[f"contract:{track}"]))
            if track in pkg.music and not set(pkg.music[track]["moods"]) & set(aud["music_moods"]):
                out.append(finding("CRE-002", WARNING, None, f"Music bed {track} ({pkg.music[track]['moods']}) does not match "
                                   f"the audience's intended moods {aud['music_moods']}; no cleared track does",
                                   approval="editorial: music selection"))

        usable = {r["insight_id"]: r for r in self.insight_review.get(aud["audience_id"], [])}
        for ins in plan.get("insights_used", []):
            row = usable.get(ins)
            if row is None:
                out.append(finding("PER-001", ERROR, None, f"Insight '{ins}' is not an insight for this audience", fix="drop_insight", refs=[ins]))
            elif not row["usable"]:
                out.append(finding("PER-001", ERROR, None, f"Insight '{ins}' failed bias review: {'; '.join(row['flags'])}",
                                   fix="drop_insight", refs=[ins]))

        rating = self.pol["rating_policies"][aud["rating_policy"]]
        if rating.get("avoid_misleading_intensity") and total > 0:
            intense = set(self.pol["intensity"]["intense_tags"])
            ep_total = sum(s.end_s - s.start_s for s in pkg.episode.scenes)
            ep_share = sum(s.end_s - s.start_s for s in pkg.episode.scenes if intense & set(s.tags)) / ep_total
            tr_share = sum(d for s, d in zip(segs, durations)
                           if pkg.scene(s.get("video")) and intense & set(pkg.scene(s["video"]).tags)) / total
            if tr_share > ep_share + self.pol["intensity"]["max_excess_share"]:
                out.append(finding("TRU-003", WARNING, None, f"{tr_share:.0%} of the trailer is high-intensity content versus "
                                   f"{ep_share:.0%} of the episode; may oversell intensity", approval="editorial: tone check"))

        if aud.get("dialect_audience"):
            cultural = [s for s in segs if pkg.scene(s.get("video")) and (
                set(pkg.scene(s["video"]).tags) & set(self.pol["dialect"]["cultural_evidence_tags"]) or pkg.scene(s["video"]).cultural_notes)]
            if not cultural:
                out.append(finding("DIA-004", WARNING, None, "No segment shows dialect or cultural context",
                                   approval="cultural reviewer"))
            spoken = [s for s in segs if s.get("subtitle")]
            comic = [s for s in spoken if "humour" in pkg.scene(s["video"]).tags]
            if spoken and len(comic) / len(spoken) > self.pol["dialect"]["comic_device_max_share"]:
                out.append(finding("DIA-003", WARNING, None, f"{len(comic)}/{len(spoken)} dialect lines come from comic scenes; "
                                   "dialect may read as a comic device", approval="cultural reviewer"))

        if self.spoiler_coverage == "editorial_only" and any(s.get("dialogue") or s.get("subtitle") for s in segs):
            out.append(finding("SPL-004", WARNING, None, "Spoiler map was built from editorial scene tags only (no verified "
                               "story analysis); a line that reveals a protected fact outside a tagged scene cannot be "
                               "detected automatically", approval="editorial: manual spoiler review of every dialogue line"))
        if not plan.get("audience_promise") or len(segs) < 4:
            out.append(finding("CRE-001", WARNING, None, "Plan lacks an audience promise or has fewer than 4 beats",
                               approval="editorial: structure"))
        if plan.get("cost", {}).get("budget_exceeded"):
            out.append(finding("BUD-001", ERROR, None, "Planning exceeded the configured budget"))
        return out
