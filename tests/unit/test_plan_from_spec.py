"""A saved block's generation spec → a plan (Library → Open in Timeline):
the plan re-makes the same song (same form, same seed), for the Christmas
samples (tune-planned), older full-song specs whose genre template has
changed since, and Funk Fusion; specs that can't be re-made say why."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.api.arrangement import build_sections, drop_sections  # noqa: E402
from src.api.schemas import GenerateRequest  # noqa: E402
from src.composition import christmas  # noqa: E402
from src.composition import song_plan as sp  # noqa: E402

from tests.unit.test_sessions import XMAS_SPEC  # noqa: E402

# An older Funk "full song": its form (two vamps, a break) is no longer the
# genre's template.
OLD_FUNK = {
    "genre": "funk_full_song", "key": "D#", "scale": "dorian", "tempo": 100.0, "time_signature": [4, 4],
    "seed": 247681, "swing": None,
    "instruments": ["drum_kit", "electric_bass", "electric_piano", "electric_guitar_clean", "synth_bass",
                    "piano", "acoustic_guitar", "synth_pad"],
    "sections": [{"start_bar": 0, "end_bar": 3, "label": "Intro", "role": "intro"},
                 {"start_bar": 4, "end_bar": 19, "label": "Vamp A", "role": "verse"},
                 {"start_bar": 20, "end_bar": 23, "label": "Break", "role": "bridge"},
                 {"start_bar": 24, "end_bar": 39, "label": "Vamp B", "role": "verse"},
                 {"start_bar": 40, "end_bar": 47, "label": "Bridge", "role": "bridge"},
                 {"start_bar": 48, "end_bar": 63, "label": "Outro vamp", "role": "outro"}],
    "section": None,
}
FUNK_FUSION = {
    "genre": "funk_fusion_full", "key": "Eb", "scale": "major", "tempo": 120.0, "time_signature": [4, 4],
    "seed": 617891, "swing": None,
    "instruments": ["drum_kit", "electric_bass", "electric_piano", "trumpet", "trombone", "synth_lead",
                    "string_section", "french_horn"],
    "section_presets": {}, "section_overrides": {"verse": {"energy": 0.7}},
    "sections": [{"start_bar": 0, "end_bar": 3, "label": "Intro", "role": "intro"},
                 {"start_bar": 4, "end_bar": 11, "label": "Verse", "role": "verse"},
                 {"start_bar": 12, "end_bar": 19, "label": "Chorus 1", "role": "chorus"},
                 {"start_bar": 20, "end_bar": 23, "label": "Bridge", "role": "bridge"},
                 {"start_bar": 24, "end_bar": 31, "label": "Chorus 2", "role": "chorus"},
                 {"start_bar": 32, "end_bar": 33, "label": "Outro", "role": "outro"}],
    "section": None, "arrangement": "hits_only,simple_bass", "lead_patch": "horns", "target_lufs": -24,
}


def _form(plan: dict) -> list[tuple]:
    if plan["genre"] in christmas.STYLE_IDS:
        secs = christmas.plan_song(plan["genre"], seed=plan["seed"], tune=plan.get("tune"), key=plan.get("key"),
                                   tempo=plan.get("tempo"), arrangement=plan.get("arrangement", ""))["sections"]
        secs = drop_sections(secs, plan.get("remove_sections"))
    else:
        secs = build_sections(plan["genre"], plan.get("sections") or [], plan.get("section_presets"),
                              plan.get("section_overrides"), plan.get("remove_sections"),
                              plan.get("section_layout"))
    return sp._layout(secs)


class PlanFromSpecTests(unittest.TestCase):
    def test_christmas_sample(self):
        plan = sp.plan_from_spec(XMAS_SPEC)
        self.assertEqual(plan["genre"], "christmas_pop_full")
        self.assertEqual((plan["seed"], plan["tune"]), (446200, "original"))
        self.assertNotIn("key", plan)          # the tune's own key and tempo come back from the seed
        self.assertNotIn("tempo", plan)
        self.assertEqual(_form(plan), sp._layout(XMAS_SPEC["sections"]))
        GenerateRequest.model_validate(plan)

    def test_christmas_with_a_chosen_key_keeps_it(self):
        spec = {**XMAS_SPEC, "key": "C"}
        self.assertEqual(sp.plan_from_spec(spec)["key"], "C")

    def test_christmas_with_recorded_plan_args(self):
        # Newer blocks record the tune's plan inputs, a removed section included.
        spec = {**XMAS_SPEC, "sections": XMAS_SPEC["sections"][:1] + XMAS_SPEC["sections"][2:],
                "plan_args": {"genre": "christmas_pop_full", "seed": 446200, "tune": "original", "key": None,
                              "tempo": None, "length_seconds": None, "arrangement": "", "remove_sections": [1]}}
        plan = sp.plan_from_spec(spec)
        self.assertEqual(plan["remove_sections"], [1])
        self.assertNotIn("key", plan)
        self.assertEqual([r for r, _ in _form(plan)], ["intro", "outro"])
        GenerateRequest.model_validate(plan)

    def test_older_funk_keeps_its_own_form(self):
        plan = sp.plan_from_spec(OLD_FUNK)
        self.assertEqual(plan["seed"], 247681)
        self.assertEqual(plan["key"], "D#")
        self.assertEqual([x["label"] for x in plan["section_layout"]],
                         ["Intro", "Vamp A", "Break", "Vamp B", "Bridge", "Outro vamp"])
        self.assertEqual(_form(plan), sp._layout(OLD_FUNK["sections"]))
        # Remove a section on the timeline: indices into that same form.
        cut = _form({**plan, "remove_sections": [2]})
        self.assertEqual([r for r, _ in cut], ["intro", "verse", "verse", "bridge", "outro"])
        GenerateRequest.model_validate(plan)

    def test_funk_fusion_keeps_its_engine_options(self):
        plan = sp.plan_from_spec(FUNK_FUSION)
        self.assertEqual(sp.split_variants(plan["arrangement"]), ["hits_only", "simple_bass"])
        self.assertEqual(plan["lead_patch"], "horns")
        self.assertEqual(plan["target_lufs"], -24)
        self.assertEqual(plan["section_overrides"]["verse"]["energy"], 0.7)
        self.assertEqual(_form(plan), sp._layout(FUNK_FUSION["sections"]))

    def test_revising_keeps_the_form_until_the_sections_change(self):
        plan = sp.plan_from_spec(OLD_FUNK)
        kept, _ = sp.normalize_plan({"tempo": 90}, plan)
        self.assertEqual(kept["section_layout"], plan["section_layout"])
        self.assertEqual(kept["tempo"], 90)
        changed, _ = sp.normalize_plan({"sections": ["intro", "verse", "outro"]}, plan)
        self.assertNotIn("section_layout", changed)

    def test_specs_that_cant_be_remade_say_why(self):
        for spec, why in ((None, "No generation settings"), ({}, "No generation settings"),
                          ({"genre": "pop", "inferred": True}, "guessed"),
                          ({"genre": "no_such_style"}, "no longer available")):
            with self.assertRaises(sp.PlanError) as cm:
                sp.plan_from_spec(spec)
            self.assertIn(why, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
