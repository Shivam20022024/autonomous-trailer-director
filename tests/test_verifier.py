"""The verifier must be able to reject a creative plan on every constraint in the brief."""
from conftest import errors, segment, warnings

from trailer_director.text_rules import vocative_kinship_terms


def check(ctx, audience_id, seg):
    return ctx.verifier.check_segment(seg, ctx.pkg.audience(audience_id))


# ---- source accuracy (required: missing scene) -------------------------------

def test_missing_scene_is_rejected(ctx):
    seg = segment(ctx, "young_adult", ref="scene:scene_14", video="scene_14",
                  tc_in="00:15:10.000", tc_out="00:15:14.000")
    found = errors(check(ctx, "young_adult", seg), "SRC-001")
    assert found and found[0]["fix"] == "replace_clip"


def test_timecode_outside_scene_is_rejected(ctx):
    seg = segment(ctx, "family", video="scene_02", tc_in="00:05:00.000", tc_out="00:05:03.000")
    assert errors(check(ctx, "family", seg), "SRC-002")


def test_misquoted_dialogue_is_rejected(ctx):
    seg = segment(ctx, "family", ref="line:d02_3")
    seg["dialogue"][0]["text"] = "Come inside. Your inheritance is waiting."
    assert errors(check(ctx, "family", seg), "SRC-004")


# ---- rights (required: rights restriction) ------------------------------------

def test_uncleared_source_music_in_original_mix_is_rejected(ctx):
    seg = segment(ctx, "family", ref="moment:m06b", audio="original_mix")
    found = errors(check(ctx, "family", seg), "RGT-001")
    assert found and all(f["fix"] == "use_dialogue_stem" for f in found)


def test_uncleared_trailer_music_is_rejected(ctx):
    seg = segment(ctx, "family", ref="moment:m01a", bed="music-03")
    assert any("not cleared for promotional use" in f["message"] for f in errors(check(ctx, "family", seg), "RGT-001"))


def test_actor_voice_restriction(ctx):
    seg = segment(ctx, "young_adult", ref="line:d09_3")
    assert errors(check(ctx, "young_adult", seg), "RGT-003")
    muted = segment(ctx, "young_adult", ref="line:d09_3", audio="music_only")
    assert not errors(check(ctx, "young_adult", muted), "RGT-003")


def test_actor_territory_restriction_is_market_specific(ctx):
    seg_dialect = segment(ctx, "dialect_region", ref="moment:m03b")
    seg_family = segment(ctx, "family", ref="moment:m03b")
    assert errors(check(ctx, "dialect_region", seg_dialect), "RGT-002")
    assert not errors(check(ctx, "family", seg_family), "RGT-002")


def test_minor_on_screen_needs_legal_signoff(ctx):
    seg = segment(ctx, "family", ref="moment:m02b")
    assert warnings(check(ctx, "family", seg), "RGT-004")


# ---- spoilers (required) ------------------------------------------------------

def test_spoiler_scene_is_rejected(ctx):
    seg = segment(ctx, "young_adult", ref="line:d10_1")
    assert errors(check(ctx, "young_adult", seg), "SPL-001")


def test_spoiler_line_inside_safe_scene_is_rejected_and_trimmable(ctx):
    seg = segment(ctx, "family", video="scene_08", tc_in="00:10:03.000", tc_out="00:10:11.000", audio="dialogue_and_music")
    found = errors(check(ctx, "family", seg), "SPL-001")
    assert found and found[0]["fix"] == "trim" and found[0]["refs"] == ["line:d08_3"]


def test_spoiler_in_text_card_is_rejected(ctx):
    seg = segment(ctx, "young_adult", ref="moment:m07b", text_card={"text": "What if Bebe hid the will?", "seconds": 3.0})
    assert errors(check(ctx, "young_adult", seg), "SPL-002")


def test_spoiler_implied_by_clip_order_is_rejected(ctx):
    aud = ctx.pkg.audience("young_adult")
    a = segment(ctx, "young_adult", ref="line:d09_2")
    b = segment(ctx, "young_adult", ref="moment:m09b")
    b["segment_id"] = "young_adult_t02"
    plan = {"audience_id": "young_adult", "audience_promise": "x", "segments": [a, b],
            "music_plan": {"bed_track": "music-01"}, "insights_used": []}
    assert errors(ctx.verifier.check_plan(plan, aud), "SPL-003")
    plan["segments"] = [b, a]
    assert not errors(ctx.verifier.check_plan(plan, aud), "SPL-003")


def test_editorial_spoiler_tag_protects_scene_the_model_missed(ctx):
    facts = {f["fact_id"]: f for f in ctx.spoiler_map["protected_facts"]}
    assert facts["EDITORIAL-scene_11"]["source"] == "editorial_tag"
    seg = segment(ctx, "family", ref="moment:m11b")
    assert errors(check(ctx, "family", seg), "SPL-001")


# ---- ratings / policy (required: policy failure) ------------------------------

def test_family_policy_rejects_frightening_shot(ctx):
    seg = segment(ctx, "family", ref="moment:m05a")
    msgs = [f["message"] for f in errors(check(ctx, "family", seg), "RAT-001")]
    assert any("frightening" in m for m in msgs) and any("jump_scare" in m for m in msgs)


def test_ai_description_adds_caution_the_human_description_lacks(ctx):
    """scene_07's AI description says 'blood'; the human one does not. Treat it as blood for the dialect market."""
    seg = segment(ctx, "dialect_region", ref="moment:m07a")
    assert any("'blood'" in f["message"] for f in errors(check(ctx, "dialect_region", seg), "RAT-001"))
    assert warnings(check(ctx, "dialect_region", seg), "DESC-001")


def test_caution_content_is_a_warning_not_an_error(ctx):
    found = check(ctx, "family", segment(ctx, "family", ref="line:d04_2"))
    assert warnings(found, "RAT-002") and not errors(found)


def test_family_forbidden_words_in_text(ctx):
    seg = segment(ctx, "family", ref="moment:m01a", text_card={"text": "A house full of blood.", "seconds": 2.5})
    assert errors(check(ctx, "family", seg), "RAT-003")


# ---- story truth, dialect, bias -----------------------------------------------

def test_clickbait_claim_not_supported_by_episode(ctx):
    seg = segment(ctx, "young_adult", ref="line:d06_1", text_card={"text": "Who will DIE for the inheritance?", "seconds": 3.0})
    assert errors(check(ctx, "young_adult", seg), "TRU-001")


def test_dialect_subtitle_that_changes_relationship_is_rejected(ctx):
    seg = segment(ctx, "dialect_region", ref="line:d08_1", subtitle_track="dialect_b")
    found = errors(check(ctx, "dialect_region", seg), "TRU-002")
    assert found and "granddaughter" in found[0]["message"]
    ok = segment(ctx, "dialect_region", ref="line:d08_1", subtitle_track="dialect_a")
    assert not errors(check(ctx, "dialect_region", ok))


def test_kinship_term_mentioned_not_addressed_is_ignored():
    lex = {"dadi": ["grandmother"], "beti": ["granddaughter"]}
    assert vocative_kinship_terms("The trust would have sold the house and sent Dadi away.", lex) == []
    assert vocative_kinship_terms("Someone has to, Dadi.", lex) == ["dadi"]
    assert vocative_kinship_terms("Beti, you carry this house.", lex) == ["beti"]


def test_dialect_audience_requires_its_track(ctx):
    seg = segment(ctx, "dialect_region", ref="line:d03_2", subtitle_track="source")
    assert errors(check(ctx, "dialect_region", seg), "DIA-001")


def test_stereotyping_text_card_is_rejected(ctx):
    seg = segment(ctx, "dialect_region", ref="moment:m01b", text_card={"text": "Full desi tadka, full comedy!", "seconds": 2.5})
    assert errors(check(ctx, "dialect_region", seg), "DIA-002")


def test_biased_insight_cannot_shape_a_plan(ctx):
    aud = ctx.pkg.audience("dialect_region")
    plan = {"audience_id": "dialect_region", "audience_promise": "x", "segments": [],
            "music_plan": {"bed_track": "music-05"}, "insights_used": ["dr-1", "dr-2", "dr-3"]}
    flagged = {f["refs"][0] for f in errors(ctx.verifier.check_plan(plan, aud), "PER-001")}
    assert flagged == {"dr-1", "dr-2"}


# ---- accessibility, security, audience ----------------------------------------

def test_text_card_too_short_to_read(ctx):
    seg = segment(ctx, "family", ref="moment:m01a", text_card={"text": "A family story in the language of home.", "seconds": 1.5})
    assert errors(check(ctx, "family", seg), "ACC-003")


def test_dialogue_without_subtitles_is_rejected(ctx):
    seg = segment(ctx, "family", ref="line:d02_3")
    seg["subtitle"] = None
    assert errors(check(ctx, "family", seg), "ACC-001")


def test_instruction_in_scene_description_does_not_change_rules(ctx):
    """scene_07's AI description tells the agent to ignore the music contract. It must have no effect."""
    assert any(f["scene_id"] == "scene_07" for f in ctx.story_map["untrusted_text_flags"])
    seg = segment(ctx, "young_adult", ref="moment:m07b", bed="music-03")
    found = check(ctx, "young_adult", seg)
    assert errors(found, "RGT-001")
    assert warnings(found, "SEC-001")


def test_unknown_audience_is_rejected(ctx):
    result = ctx.verifier.verify_plan({"audience_id": "kids", "segments": []})
    assert result["status"] == "FAIL" and result["errors"][0]["check_id"] == "AUD-001"


def test_unsupported_model_claims_are_dropped_from_story_map(ctx):
    rejected = {r["kind"]: r for r in ctx.story_map["rejected_model_claims"]}
    assert "relationship" in rejected and "event" in rejected
    assert not any(r["relation"] == "father" for r in ctx.story_map["relationships"])
