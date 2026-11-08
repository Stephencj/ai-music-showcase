"""Song plans (src/composition/song_plan.py): validation of interpreter output,
robust parsing of model text, the rule-based fallback, and the guide."""

import json

import pytest

from src.api.schemas import GenerateRequest
from src.composition import song_plan as sp
from src.composition.funk_fusion import ARRANGEMENT_VARIANTS

FF = "funk_fusion_full"


# --- normalize_plan -----------------------------------------------------------
def test_valid_fusion_plan_passes_through():
    raw = {"genre": FF, "tempo": 120, "key": "Eb", "scale": "major",
           "arrangement": "hits_only,calm_keys,simple_bass", "lead_patch": "guitar_stack",
           "hits": [3.9, 7.0], "hit_style": "groove", "target_lufs": -25}
    plan, notes = sp.normalize_plan(raw)
    assert notes == []
    assert plan["arrangement"] == "hits_only,calm_keys,simple_bass"
    assert plan["lead_patch"] == "guitar_stack" and plan["hits"] == [3.9, 7.0]
    assert plan["target_lufs"] == -25.0 and plan["hit_style"] == "groove"
    GenerateRequest.model_validate(plan)


def test_unknown_options_dropped_with_notes_and_numbers_clamped():
    plan, notes = sp.normalize_plan({
        "genre": FF, "tempo": 999, "target_lufs": -90, "swing": 3, "key": "H#",
        "scale": "klingon", "arrangement": "calm_keys, cowbell_solo", "lead_patch": "kazoo",
        "instruments": ["drum_kit", "theremin"], "hit_style": "sideways",
        "section_overrides": {"verse": {"energy": 9, "arrangement": "calm,laser"}, "solo": {"energy": 1}},
        "nonsense": 1,
    })
    assert plan["tempo"] == 260 and plan["target_lufs"] == -40 and plan["swing"] == 0.6
    assert "key" not in plan and "scale" not in plan and "lead_patch" not in plan
    assert "hit_style" not in plan
    assert plan["arrangement"] == "calm_keys"
    assert plan["instruments"] == ["drum_kit"]
    assert plan["section_overrides"] == {"verse": {"energy": 1.5, "arrangement": "calm"}}
    text = " ".join(notes)
    for word in ("cowbell_solo", "laser", "kazoo", "theremin", "H#", "klingon"):
        assert word in text


def test_unknown_genre_falls_back_and_aliases_resolve():
    plan, notes = sp.normalize_plan({"genre": "space polka"})
    assert plan["genre"] == "pop_full_song" and notes
    assert sp.normalize_plan({"genre": "Funk Fusion"})[0]["genre"] == FF
    assert sp.normalize_plan({"genre": "funk-fusion"})[0]["genre"] == FF


def test_compose_song_genres_drop_fusion_only_options():
    plan, notes = sp.normalize_plan({"genre": "rock_anthem_full", "arrangement": "simple_bass",
                                     "lead_patch": "horns", "hits": [1.0], "target_lufs": -24})
    assert "arrangement" not in plan and "lead_patch" not in plan and "hits" not in plan
    assert plan["target_lufs"] == -24          # loudness works on every engine
    assert len(notes) == 3
    assert sp.engine_for("rock_anthem_full").id == "compose_song"
    assert sp.engine_for(FF).id == "funk_fusion"


def test_variants_bring_their_instruments():
    plan, _ = sp.normalize_plan({"genre": FF, "arrangement": "soar"})
    assert {"string_section", "french_horn"} <= set(plan["instruments"])
    assert "drum_kit" in plan["instruments"]          # the default band stays
    plan, _ = sp.normalize_plan({"genre": FF, "section_overrides": {"intro": {"arrangement": "string_intro"}}})
    assert "string_spiccato" in plan["instruments"]


def test_one_bass_variant_and_the_new_one_wins():
    prev = {"genre": FF, "arrangement": "hits_only,pocket_bass"}
    plan, _ = sp.normalize_plan({"arrangement": "hits_only,pocket_bass,simple_bass"}, prev)
    assert plan["arrangement"] == "hits_only,simple_bass"
    # Shorthand "calm" breaks up when a revision asks for pocket drums.
    prev = {"genre": FF, "arrangement": "calm"}
    plan, _ = sp.normalize_plan({"arrangement": "calm,pocket_drums"}, prev)
    assert set(plan["arrangement"].split(",")) == {"calm_bass", "calm_keys", "pocket_drums"}
    # Without a conflict "calm" stays as is.
    assert sp.normalize_plan({"genre": FF, "arrangement": "calm,hits_only"})[0]["arrangement"] == "hits_only,calm"


def test_revision_keeps_unmentioned_fields_and_null_removes():
    prev = {"genre": FF, "tempo": 120, "arrangement": "hits_only", "target_lufs": -25, "hits": []}
    plan, _ = sp.normalize_plan({"arrangement": "hits_only,brushes", "target_lufs": None}, prev)
    assert plan["tempo"] == 120 and plan["hits"] == []
    assert plan["arrangement"] == "hits_only,brushes"
    assert "target_lufs" not in plan


def test_not_a_plan_raises():
    with pytest.raises(sp.PlanError):
        sp.normalize_plan(["genre", FF])
    with pytest.raises(sp.PlanError):
        sp.normalize_plan({"mood": "happy"})


def test_section_builder_settings_survive():
    ov = {"verse": {"progression": ["i7", "iv7"], "instruments": ["drum_kit", "bogus"], "bars": 4}}
    plan, _ = sp.normalize_plan({"genre": FF, "section_overrides": ov})
    assert plan["section_overrides"]["verse"] == {"bars": 4, "progression": ["i7", "iv7"],
                                                  "instruments": ["drum_kit"]}


# --- parse_model_output -------------------------------------------------------
PLAN = {"genre": FF, "arrangement": "simple_bass"}


@pytest.mark.parametrize("text", [
    json.dumps({"plan": PLAN, "summary": "ok"}),
    "Sure! Here's the plan:\n```json\n" + json.dumps({"plan": PLAN, "summary": "ok"}) + "\n```\nEnjoy.",
    "<think>the bass is busy so simple_bass</think>" + json.dumps({"plan": PLAN, "summary": "ok"}),
    '{"plan": {"genre": "funk_fusion_full", "arrangement": "simple_bass",}, "summary": "ok",}',
    '<tool_call>{"name": "song_plan", "arguments": ' + json.dumps(json.dumps({"plan": PLAN, "summary": "ok"})) + "}</tool_call>",
    json.dumps({"function": {"name": "song_plan", "arguments": json.dumps({"plan": PLAN, "summary": "ok"})}}),
    "{'not': json} then " + json.dumps({"plan": PLAN, "summary": "ok"}),
])
def test_parse_model_output_variants(text):
    plan, summary = sp.parse_model_output(text)
    assert plan == PLAN and summary == "ok"


def test_parse_bare_plan_and_dict():
    assert sp.parse_model_output(json.dumps(PLAN))[0] == PLAN
    assert sp.parse_model_output({"plan": PLAN, "summary": "s"}) == (PLAN, "s")


@pytest.mark.parametrize("bad", ["", "I can't help with that.", "{broken", None, "[1, 2]", '{"mood": "sad"}'])
def test_parse_garbage_raises(bad):
    with pytest.raises(sp.PlanError):
        sp.parse_model_output(bad)


# --- rules --------------------------------------------------------------------
BED = {"genre": FF, "tempo": 120.0, "arrangement": "hits_only,calm_keys,pocket_bass,calm_drums"}


@pytest.mark.parametrize("feedback,check", [
    ("the bass is doing too much", lambda p: "simple_bass" in p["arrangement"] and "pocket_bass" not in p["arrangement"]),
    ("too many fills", lambda p: "pocket_drums" in p["arrangement"] and "calm_drums" not in p["arrangement"]),
    ("no stabs", lambda p: p["hits"] == []),
    ("it's background, lower the volume", lambda p: p["target_lufs"] == -25),
    ("drums are too percussive", lambda p: "brushes" in p["arrangement"]),
    ("make it soar", lambda p: "soar" in p["arrangement"] and "string_section" in p["instruments"]),
    ("the fall-off makes it seem silly", lambda p: "no_falloff" in p["arrangement"]),
    ("too fast", lambda p: p["tempo"] < 120),
    ("NO trumpet, just end on the strings", lambda p: "trumpet" not in p["instruments"]
     and {"soar", "no_falloff"} <= set(p["arrangement"].split(","))),
    ("calm with an occasional flare in the bass", lambda p: "bass_flare" in p["arrangement"]),
    ("less complex, more impactful", lambda p: "hits_only" in p["arrangement"]),
    ("make it 100 bpm in G minor", lambda p: p["tempo"] == 100 and p["key"] == "G" and p["scale"] == "minor"),
])
def test_rule_revise_maps_history_feedback(feedback, check):
    raw, fired = sp.rule_revise(BED, feedback)
    plan, _ = sp.normalize_plan(raw, BED)
    assert check(plan), (feedback, plan)


def test_rule_revise_bass_ladder_steps_down_twice():
    p1, _ = sp.normalize_plan(sp.rule_revise(BED, "bass too busy")[0], BED)
    p2, _ = sp.normalize_plan(sp.rule_revise(p1, "the bass is still doing too much")[0], p1)
    assert "simple_bass" in p1["arrangement"] and "calm_bass" in p2["arrangement"]


def test_rule_describe():
    raw, _, _ = sp.rule_describe("funk fusion background bed for a product video, simple bass, no stabs, 120 bpm")
    plan, _ = sp.normalize_plan(raw)
    assert plan["genre"] == FF and plan["tempo"] == 120 and plan["hits"] == []
    assert plan["target_lufs"] == -25 and plan["arrangement"] == "simple_bass"
    raw, _, _ = sp.rule_describe("a rock song in E minor without the organ, add a sax")
    plan, _ = sp.normalize_plan(raw)
    assert plan["genre"] == "rock_anthem_full" and plan["key"] == "E" and plan["scale"] == "minor"
    assert "organ_hammond" not in plan["instruments"] and "sax_tenor" in plan["instruments"]
    assert "drum_kit" in plan["instruments"]


def test_describe_changes():
    old = {"genre": FF, "arrangement": "hits_only,pocket_bass", "tempo": 120}
    new = {"genre": FF, "arrangement": "hits_only,simple_bass", "tempo": 120, "hits": [], "target_lufs": -25}
    ch = sp.describe_changes(old, new)
    assert "Arrangement: +simple_bass, −pocket_bass" in ch and "No stabs" in ch
    assert any(c.startswith("target_lufs") for c in ch)


# --- the guide ------------------------------------------------------------------
def test_guide_documents_every_option():
    guide = sp.GUIDE_PATH.read_text()
    system = sp.system_prompt()
    for v in ARRANGEMENT_VARIANTS:
        assert f"`{v}`: " in system, v
    from src.audio_processing.render.lead_voices import LEAD_VOICES
    for v in LEAD_VOICES:
        assert f"`{v}`" in guide, v
    system = sp.system_prompt()
    assert FF in system and "string_section" in system



def test_edit_style_answers():
    prev = {"genre": FF, "arrangement": "hits_only,calm_keys,pocket_bass", "tempo": 120}
    raw, _ = sp.parse_model_output('{"plan": {}, "add_variants": ["simple_bass"], '
                                   '"remove_variants": ["pocket_bass"], "summary": "s"}')
    plan, _ = sp.normalize_plan(raw, prev)
    assert plan["arrangement"] == "hits_only,calm_keys,simple_bass" and plan["tempo"] == 120
    raw, _ = sp.parse_model_output('{"plan": {"genre": "jazz_ballad_full", "add_instruments": ["sax_tenor"],'
                                   ' "remove_instruments": ["piano"]}}')
    plan, _ = sp.normalize_plan(raw)
    assert "sax_tenor" in plan["instruments"] and "piano" not in plan["instruments"]
    assert "drum_kit" in plan["instruments"]
