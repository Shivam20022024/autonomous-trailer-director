"""Robustness to how real models format replies."""
import pytest

from trailer_director.llm import parse_json_reply


def test_parses_json_wrapped_in_prose_or_fences():
    assert parse_json_reply('Here is the plan:\n{"a": 1}\nHope this helps!') == {"a": 1}
    assert parse_json_reply('```json\n{"a": 1}\n```') == {"a": 1}


def test_rejects_replies_without_a_json_object():
    with pytest.raises(ValueError):
        parse_json_reply("Sorry, I can't help with that.")


def test_malformed_proposal_shapes_do_not_crash_the_run(ctx):
    """Regression: gpt-5 returned alternate_text_cards as plain strings, which crashed the repair step."""
    aud = ctx.pkg.audience("dialect_region")
    proposal = {
        "audience_promise": "A family mystery in the voice of home.",
        "emotional_journey": "belonging",
        "music_bed": "music-05",
        "insights_used": [{"insight_id": "dr-3"}, "dr-1"],
        "alternate_text_cards": ["Every house speaks its own language.", 42],
        "segments": [
            {"beat": "hook", "source_ref": "moment:m01b", "audio": "music_only", "text_card": "Full desi tadka!"},
            {"beat": "heart", "source_ref": "line:d08_1", "voice_over": "Home remembers."},
            "not a segment",
        ],
    }
    plan = ctx.planner.assemble(aud, proposal, {"proposal": "model"})
    assert plan["emotional_journey"] == ["belonging"] and plan["insights_used"] == ["dr-3", "dr-1"]
    assert plan["alternate_text_cards"] == [{"text": "Every house speaks its own language.", "seconds": 3.0}]
    assert len(plan["segments"]) == 2
    assert plan["segments"][1]["voice_over"] == {"text": "Home remembers.", "caption": "Home remembers."}
    result = ctx.verifier.verify_plan(plan)
    actions = ctx.repairer.repair(plan, aud, result, 1)  # must not raise
    assert any(a["action"] == "replace_text_card" for a in actions)


def test_grounding_fills_only_what_the_model_left_out(ctx):
    aud = ctx.pkg.audience("family")
    seg = ctx.planner.ground_segment(aud, {"beat": "setup", "source_ref": "line:d02_3", "audio": "dialogue_and_music"},
                                     "family_t01", 1, "music-01")
    assert seg["video"] == "scene_02" and seg["source_in"] == "00:02:04.750"
    # A wrong value the model did give is kept, so the verifier can report it.
    wrong = ctx.planner.ground_segment(aud, {"beat": "setup", "source_ref": "line:d02_3", "video": "scene_09",
                                             "source_in": "00:02:04.750", "source_out": "00:02:08.850"},
                                       "family_t02", 1, "music-01")
    assert wrong["video"] == "scene_09"
    assert any(f["check_id"] == "SRC-002" for f in ctx.verifier.check_segment(wrong, aud))
