"""Audience-insight review: question correlations before the planner may use them."""


def review_insights(pkg) -> dict:
    th = pkg.policies["bias_thresholds"]
    protected_tags = set(pkg.policies["spoiler_policy"]["protected_scene_tags"])
    review = {}
    for aud_id, profile in pkg.profiles.items():
        rows = []
        for ins in profile["insights"]:
            flags = []
            if ins.get("exposure_share", 0) > th["max_exposure_share"]:
                flags.append(f"exposure_bias: {ins['exposure_share']:.0%} of earlier promos shown to this segment were of the "
                             "favoured type, so the lift may reflect what was shown rather than what viewers prefer")
            if ins.get("sample_size", 0) < th["min_sample_size"]:
                flags.append(f"small_sample: n={ins.get('sample_size')} < {th['min_sample_size']}")
            sensitive = sorted(set(ins.get("segment_attributes", [])) & set(th["sensitive_attributes"]))
            if sensitive:
                flags.append(f"sensitive_attribute: segments viewers by {sensitive}; personalising on this risks a social stereotype")
            conflict = sorted(set(ins.get("implication", {}).get("prefer_tags", [])) & protected_tags)
            if conflict:
                flags.append(f"policy_conflict: recommends {conflict} content, which the spoiler policy protects")
            rows.append({"insight_id": ins["insight_id"], "claim": ins["claim"], "metric": ins.get("metric"),
                         "usable": not flags, "flags": flags,
                         "prefer_tags": ins.get("implication", {}).get("prefer_tags", [])})
        review[aud_id] = rows
    return review


def usable_insights(review: dict, audience_id: str) -> list[dict]:
    return [r for r in review.get(audience_id, []) if r["usable"]]
