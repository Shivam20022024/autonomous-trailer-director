"""Constraint map: policies and contracts turned into testable rules linked to
scenes, lines, moments, actors, music and markets.

The map is a planning and traceability artefact. The verifier does not read it;
it re-derives every decision from the source files so a mistake here cannot
silently weaken verification.
"""
from .text_rules import description_tags


def build_constraint_map(pkg, spoiler_map: dict, bias_review: dict) -> dict:
    rules = []

    def add(rule_id, category, statement, source, applies_to, severity="error", check=None):
        rules.append({"rule_id": rule_id, "category": category, "statement": statement, "source": source,
                      "applies_to": applies_to, "severity": severity, "verified_by": check})

    markets = list(pkg.contracts["markets"])
    auds_in = {m: [a for a, d in pkg.audiences.items() if d["market"] == m] for m in markets}

    for tid, t in pkg.music.items():
        src_scenes = [s.scene_id for s in pkg.episode.scenes if s.source_music == tid]
        for m in markets:
            problems = pkg.music_problems(tid, m)
            if problems:
                add(f"RGT-MUSIC-{tid}-{m}", "rights", "; ".join(problems), f"contracts.json#music/{tid}",
                    {"music": [tid], "markets": [m], "audiences": auds_in[m], "scenes_with_source_music": src_scenes},
                    check="RGT-001")

    for aid, a in pkg.actors.items():
        ch = a["plays"]
        scenes = [s.scene_id for s in pkg.episode.scenes if ch in s.characters_present]
        lines = [l.line_id for s in pkg.episode.scenes for l in s.dialogue if l.speaker == ch]
        base = {"actors": [aid], "characters": [ch], "scenes": scenes}
        if not a["promo_video"]:
            add(f"RGT-ACTOR-{aid}-VIDEO", "rights", f"{ch} ({aid}) may not appear on screen in promos",
                f"contracts.json#actors/{aid}", base, check="RGT-002")
        if not a["promo_voice"]:
            add(f"RGT-ACTOR-{aid}-VOICE", "rights", f"{ch}'s voice ({aid}) may not be heard in promos",
                f"contracts.json#actors/{aid}", {**base, "lines": lines}, check="RGT-003")
        for m in markets:
            if m not in a["territories"]:
                add(f"RGT-ACTOR-{aid}-TERRITORY-{m}", "rights", f"{ch} ({aid}) is not cleared in market '{m}'",
                    f"contracts.json#actors/{aid}", {**base, "markets": [m], "audiences": auds_in[m]}, check="RGT-002")
        if a.get("minor"):
            add(f"RGT-ACTOR-{aid}-MINOR", "rights", f"{ch} is a minor; every promo use needs legal sign-off",
                f"contracts.json#actors/{aid}", base, severity="human_approval", check="RGT-004")

    sens = pkg.policies["sensitive_description_terms"]
    for aud_id, aud in pkg.audiences.items():
        pol = pkg.policies["rating_policies"][aud["rating_policy"]]
        for tag in pol["forbidden_tags"]:
            scenes = [s.scene_id for s in pkg.episode.scenes if tag in set(s.tags) | description_tags(s, sens)]
            if scenes:
                add(f"RAT-{aud_id}-TAG-{tag}", "rating", f"'{tag}' content is not allowed for {aud['label']}",
                    f"policies.json#rating_policies/{aud['rating_policy']}", {"audiences": [aud_id], "scenes": scenes}, check="RAT-001")
        for tag in pol["caution_tags"]:
            scenes = [s.scene_id for s in pkg.episode.scenes if tag in s.tags]
            if scenes:
                add(f"RAT-{aud_id}-CAUTION-{tag}", "rating", f"'{tag}' content needs standards review for {aud['label']}",
                    f"policies.json#rating_policies/{aud['rating_policy']}", {"audiences": [aud_id], "scenes": scenes},
                    severity="warning", check="RAT-002")
        for vtag in pol["forbidden_visual_tags"]:
            moments = [m.moment_id for s in pkg.episode.scenes for m in s.moments if vtag in m.visual_tags]
            if moments:
                add(f"RAT-{aud_id}-VISUAL-{vtag}", "rating", f"'{vtag}' shots are not allowed for {aud['label']}",
                    f"policies.json#rating_policies/{aud['rating_policy']}", {"audiences": [aud_id], "moments": moments}, check="RAT-001")
        if pol["forbidden_words"]:
            add(f"RAT-{aud_id}-WORDS", "rating", f"Text cards and voice-over may not use: {pol['forbidden_words']}",
                f"policies.json#rating_policies/{aud['rating_policy']}", {"audiences": [aud_id]}, check="RAT-003")
        lo, hi = aud["target_duration_seconds"]
        add(f"TIM-{aud_id}-DURATION", "timing", f"Total duration must be {lo}-{hi}s", "audiences.json",
            {"audiences": [aud_id]}, check="TIM-001")
        add(f"ACC-{aud_id}-SUBTITLES", "accessibility",
            f"All audible dialogue must carry '{aud['subtitle_track']}' subtitles within reading-speed limits",
            "policies.json#accessibility", {"audiences": [aud_id]}, check="ACC-001/ACC-002/DIA-001")

    for f in spoiler_map["protected_facts"]:
        add(f"SPL-{f['fact_id']}", "spoiler", f"Protected fact: {f['statement']}", f"spoiler_map ({f['source']})",
            {"refs": [r["ref"] for r in f["protected_ranges"]], "forbidden_sequences": f["forbidden_sequences"],
             "text_keywords": f["text_keywords"]}, check="SPL-001/SPL-002/SPL-003")

    add("TRU-CLAIMS", "story_truth", "Text cards and voice-over may not claim deaths, ghosts, affairs etc. that the "
        "episode's human descriptions and dialogue do not support", "policies.json#claim_lexicon", {}, check="TRU-001")
    add("TRU-RELATIONSHIPS", "story_truth", "Subtitles may not change a relationship established in the story map",
        "policies.json#kinship_lexicon", {}, check="TRU-002")
    add("DIA-STEREOTYPE", "cultural_respect", "No stereotyping language in text cards or voice-over",
        "policies.json#stereotype_lexicon", {}, check="DIA-002")
    add("PER-INSIGHTS", "bias", "Only bias-reviewed audience insights may shape a plan",
        "audience_profiles.json + policies.json#bias_thresholds",
        {"excluded": {a: [r["insight_id"] for r in rows if not r["usable"]] for a, rows in bias_review.items()}}, check="PER-001")

    return {"rules": rules, "scene_eligibility": _eligibility(pkg, rules, spoiler_map)}


def _eligibility(pkg, rules, spoiler_map):
    """Per audience and scene: blocked / restricted / caution / open, with the rule ids responsible."""
    whole_scene_spoilers = {r["scene_id"]: f["fact_id"] for f in spoiler_map["protected_facts"]
                            for r in f["protected_ranges"] if r["ref"].startswith("scene:")}
    partial_spoilers = {}
    for f in spoiler_map["protected_facts"]:
        for r in f["protected_ranges"]:
            if not r["ref"].startswith("scene:"):
                partial_spoilers.setdefault(r["scene_id"], []).append(f"SPL-{f['fact_id']}")
    out = {}
    for aud_id in pkg.audiences:
        table = {}
        for s in pkg.episode.scenes:
            blocking, restricting, caution = [], list(partial_spoilers.get(s.scene_id, [])), []
            if s.scene_id in whole_scene_spoilers:
                blocking.append(f"SPL-{whole_scene_spoilers[s.scene_id]}")
            for r in rules:
                ap = r["applies_to"]
                if ap.get("audiences") and aud_id not in ap["audiences"]:
                    continue
                if r["rule_id"].startswith(f"RAT-{aud_id}-TAG-") and s.scene_id in ap.get("scenes", []):
                    blocking.append(r["rule_id"])
                elif r["rule_id"].startswith(f"RAT-{aud_id}-CAUTION-") and s.scene_id in ap.get("scenes", []):
                    caution.append(r["rule_id"])
                elif r["category"] == "rights" and r["severity"] == "error" and (
                        s.scene_id in ap.get("scenes", []) or s.scene_id in ap.get("scenes_with_source_music", [])):
                    restricting.append(r["rule_id"])
                elif r["rule_id"].startswith(f"RAT-{aud_id}-VISUAL-") and any(
                        m.moment_id in ap.get("moments", []) for m in s.moments):
                    restricting.append(r["rule_id"])
            status = "blocked" if blocking else "restricted" if restricting else "caution" if caution else "open"
            table[s.scene_id] = {"status": status, "rules": sorted(set(blocking + restricting + caution))}
        out[aud_id] = table
    return out
