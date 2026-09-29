"""Story map and spoiler map.

The model proposes an analysis; this module keeps only claims whose evidence
exists in the episode package and actually supports the claim. Editorial
spoiler tags in the package are authoritative: the model can add protection,
never remove it.
"""
from .llm import ModelUnavailable
from .text_rules import description_mismatches, find_terms, injection_hits
from .timecode import fmt_tc


def analyze_episode(pkg, router, log, cached=None, recovery=None) -> tuple[dict, dict]:
    """Story analysis from the model chain.

    `cached` is used instead of a model call (change events re-use the run's analysis).
    `recovery` is used only if every model fails: an analysis remembered from an earlier
    run of the same episode. Without either, the story map falls back to editorial tags.
    """
    if cached is not None:
        log.record("analysis_reused", "Reused cached story analysis from run memory; no model call needed")
        return cached, {"model": "cache", "mode": "memory"}
    try:
        return router.call("analyze_episode", {"episode": pkg.raw["episode"],
                                               "relation_vocabulary": sorted(pkg.policies["relation_keywords"])})
    except ModelUnavailable as e:
        if recovery is not None:
            log.record("fallback", f"Story analysis unavailable ({e}); recovered the analysis remembered from a previous "
                       "run of this exact episode (fingerprint match). Its claims are re-verified below.")
            return recovery, {"model": "memory", "mode": "recovery"}
        log.record("fallback", f"Story analysis unavailable ({e}); story map will use package metadata and editorial "
                   "tags only. Line-level spoilers outside tagged scenes cannot be detected; plans will require a "
                   "manual spoiler review")
        return {}, {"model": "deterministic", "mode": "fallback"}


def _missing(pkg, refs):
    return [r for r in refs if not pkg.resolve_ref(r)]


def _evidence_text(pkg, refs):
    return " ".join(pkg.resolve_ref(r)["text"] for r in refs if pkg.resolve_ref(r))


def build_story_map(pkg, analysis: dict, meta: dict, log) -> dict:
    pol = pkg.policies
    rejected = []

    def reject(kind, claim, reason):
        rejected.append({"kind": kind, "claim": claim, "reason": reason})
        log.record("claim_rejected", f"Rejected model {kind} claim: {reason}", claim=claim)

    relationships = []
    for r in analysis.get("relationships", []):
        refs = r.get("evidence", [])
        if r.get("from") not in pkg.characters or r.get("to") not in pkg.characters:
            reject("relationship", r, "references an unknown character")
        elif not refs or _missing(pkg, refs):
            reject("relationship", r, f"evidence missing or nonexistent: {_missing(pkg, refs) or 'none cited'}")
        elif not find_terms(_evidence_text(pkg, refs), pol["relation_keywords"].get(r["relation"], [r["relation"]])):
            reject("relationship", r, f"cited evidence does not support relation '{r['relation']}'")
        else:
            relationships.append(r)

    def scene_claims(kind, items):
        kept = []
        for item in items:
            refs = item.get("evidence", [])
            if item.get("scene_id") not in pkg.scenes:
                reject(kind, item, f"scene '{item.get('scene_id')}' does not exist")
            elif not refs or _missing(pkg, refs):
                reject(kind, item, f"evidence missing or nonexistent: {_missing(pkg, refs) or 'none cited'}")
            else:
                kept.append(item)
        return kept

    events = scene_claims("event", analysis.get("events", []))
    turns = scene_claims("emotional_turn", analysis.get("emotional_turns", []))
    sensitive = scene_claims("sensitive_content", analysis.get("sensitive_content", []))

    mismatches = [m for s in pkg.episode.scenes for m in description_mismatches(s, pol["sensitive_description_terms"])]
    for m in mismatches:
        log.record("description_mismatch",
                   f"{m['scene_id']}: '{m['term']}' appears only in the "
                   f"{'AI' if m['in_ai_description'] else 'human'} description; treated conservatively as '{m['implied_tag']}' "
                   f"and flagged for human verification against the footage")

    flags = []
    for s in pkg.episode.scenes:
        for field in ("human_description", "ai_description", "cultural_notes"):
            hits = injection_hits(getattr(s, field) or "", pol["injection_patterns"])
            if hits:
                flags.append({"scene_id": s.scene_id, "field": field, "patterns": hits,
                              "excerpt": (getattr(s, field) or "")[:200]})
    for track, cues in pkg.subtitles["cues"].items():
        for line_id, text in cues.items():
            hits = injection_hits(text, pol["injection_patterns"])
            if hits:
                scene = pkg.lines[line_id][0].scene_id if line_id in pkg.lines else None
                flags.append({"scene_id": scene, "field": f"subtitle:{track}:{line_id}", "patterns": hits, "excerpt": text[:200]})
    for f in flags:
        log.record("injection_flag", f"Instruction-like text in {f['scene_id']} {f['field']} treated as data and ignored; "
                   "policies and contracts are only read from policies.json / contracts.json", flag=f)

    roles = {c["character_id"]: c.get("role") for c in analysis.get("characters", []) if isinstance(c, dict)}
    characters = [{"character_id": c.character_id, "name": c.name, "actor_id": c.actor_id,
                   "description": c.description, "role": roles.get(c.character_id)} for c in pkg.episode.characters]

    return {
        "episode_id": pkg.episode.episode_id,
        "title": pkg.episode.title,
        "analysis_source": meta,
        "characters": characters,
        "relationships": relationships,
        "events": events,
        "emotional_turns": turns,
        "sensitive_content": sensitive,
        "scene_index": [{"scene_id": s.scene_id, "title": s.title, "start": s.start_time, "end": s.end_time,
                         "tags": s.tags, "characters_present": s.characters_present,
                         "source_music": s.source_music, "cultural_notes": s.cultural_notes}
                        for s in pkg.episode.scenes],
        "description_mismatches": mismatches,
        "untrusted_text_flags": flags,
        "rejected_model_claims": rejected,
    }


def _protected_range(pkg, ref):
    r = pkg.resolve_ref(ref)
    return {"ref": ref, "scene_id": r["scene_id"], "start": fmt_tc(r["start"]), "end": fmt_tc(r["end"])}


def build_spoiler_map(pkg, analysis: dict, log) -> dict:
    facts, rejected = [], []
    for f in analysis.get("protected_facts", []):
        refs = f.get("reveal_refs", [])
        missing = _missing(pkg, refs)
        timed = [r for r in refs if r not in missing and pkg.resolve_ref(r)["start"] is not None]
        if not timed:
            reason = f"no verifiable reveal evidence (missing: {missing})"
        elif not find_terms(_evidence_text(pkg, timed), f.get("keywords", [])):
            reason = "none of the cited reveal refs contain the fact's keywords"
        else:
            reason = None
        if reason:
            rejected.append({"fact": f, "reason": reason})
            log.record("claim_rejected", f"Rejected protected fact {f.get('fact_id')}: {reason}")
            continue
        seqs = [s for s in f.get("forbidden_sequences", []) if len(s) == 2 and not _missing(pkg, s)]
        facts.append({"fact_id": f["fact_id"], "statement": f["statement"], "source": "model_verified",
                      "protected_ranges": [_protected_range(pkg, r) for r in timed],
                      "text_keywords": f.get("keywords", []), "forbidden_sequences": seqs})

    protected_tags = set(pkg.policies["spoiler_policy"]["protected_scene_tags"])
    covered = {r["ref"] for f in facts for r in f["protected_ranges"]}
    for s in pkg.episode.scenes:
        tags = protected_tags & set(s.tags)
        if tags and f"scene:{s.scene_id}" not in covered:
            facts.append({"fact_id": f"EDITORIAL-{s.scene_id}",
                          "statement": f"Editorially protected scene '{s.title}' (tags: {sorted(tags)})",
                          "source": "editorial_tag", "protected_ranges": [_protected_range(pkg, f"scene:{s.scene_id}")],
                          "text_keywords": [], "forbidden_sequences": []})
            log.record("spoiler_backfill", f"Editorial tags {sorted(tags)} on {s.scene_id} protect it although the model analysis did not")
    coverage = "story_analysis+editorial" if any(f["source"] == "model_verified" for f in facts) else "editorial_only"
    return {"policy": pkg.policies["spoiler_policy"]["statement"], "coverage": coverage, "protected_facts": facts,
            "rejected_model_facts": rejected}
