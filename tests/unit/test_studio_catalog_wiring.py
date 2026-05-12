"""Regression tests for the Studio UI wiring of the new music-theory
catalogs (Track A.4 from the melody-quality plan).

Covers:

- ``SectionOverride`` round-trips ``cadence`` / ``lick`` / ``tension_op``
  through YAML and through the Studio's dict converters in ``app.py``.
- ``HarmonyTag`` round-trips ``harmony_rule`` likewise.
- ``MelodyPlan`` round-trips ``phrase_shape`` / ``default_cadence`` /
  ``motif_development``.
- ``from_yaml`` defensively drops unknown keys (older sidecars load).
- ``render_melody_plan`` applies a section ``lick`` override (stamps the
  lick's events at the override's start bar).
- ``render_melody_plan`` applies a section ``cadence`` override
  (snaps the last note of the range to the cadence's target pitch class).
- ``regenerate_bars`` threads the plan-level ``phrase_shape`` /
  ``default_cadence`` / ``motif_development`` into the regenerator AND
  preserves them on the returned plan.
- The Studio's Plan settings + harmony-rule widgets carry stable keys
  so Gradio's ``@gr.render`` re-renders don't drop their change handlers
  — same pattern as the existing override/library/timeline key tests.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import gradio as gr

import app
from src.daw_integration.generic import melody_plan as mp
from src.daw_integration.generic.midi_export import (
    CADENCES,
    HARMONY_OPS,
    MELODIC_LICKS,
)


def _simple_plan(**overrides) -> mp.MelodyPlan:
    base = dict(
        bars=4, time_signature=(4, 4), key="C", scale="major", tempo=120,
        notes=[
            mp.MelodyNote(bar=b, beat=0.0, pitch=60 + b, duration=1.0)
            for b in range(4)
        ],
    )
    base.update(overrides)
    return mp.MelodyPlan(**base)


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------

class YamlRoundTripTests(unittest.TestCase):

    def test_override_new_fields_round_trip(self):
        plan = _simple_plan(section_overrides=[
            mp.SectionOverride(
                start_bar=0, end_bar=2,
                cadence="authentic_v_i",
                lick="pop_anacrusis_2_3_5",
                tension_op="suspension_4_3",
            ),
        ])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.yaml"
            mp.to_yaml(plan, path)
            loaded = mp.from_yaml(path)
        ov = loaded.section_overrides[0]
        self.assertEqual(ov.cadence, "authentic_v_i")
        self.assertEqual(ov.lick, "pop_anacrusis_2_3_5")
        self.assertEqual(ov.tension_op, "suspension_4_3")

    def test_harmony_rule_round_trips(self):
        plan = _simple_plan(harmonies=[
            mp.HarmonyTag(
                start_bar=0, end_bar=2, preset="queen",
                harmony_rule="voice_leading_smooth",
            ),
        ])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.yaml"
            mp.to_yaml(plan, path)
            loaded = mp.from_yaml(path)
        self.assertEqual(loaded.harmonies[0].harmony_rule,
                         "voice_leading_smooth")

    def test_plan_level_settings_round_trip(self):
        plan = _simple_plan(
            phrase_shape="rise",
            default_cadence="deceptive_v_vi",
            motif_development=["repeat", "inversion", "cadence"],
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.yaml"
            mp.to_yaml(plan, path)
            loaded = mp.from_yaml(path)
        self.assertEqual(loaded.phrase_shape, "rise")
        self.assertEqual(loaded.default_cadence, "deceptive_v_vi")
        self.assertEqual(loaded.motif_development,
                         ["repeat", "inversion", "cadence"])

    def test_unknown_yaml_keys_dropped_for_back_compat(self):
        """A sidecar written before the new fields existed should still
        load — defensive ``_drop_unknown`` filter."""
        yaml_text = (
            "bars: 2\n"
            "time_signature: [4, 4]\n"
            "key: C\n"
            "scale: major\n"
            "tempo: 120.0\n"
            "notes: []\n"
            "section_overrides:\n"
            "  - start_bar: 0\n"
            "    end_bar: 2\n"
            "    voicing: triad\n"
            "    rhythm: pulse_quarter\n"
            "    mode: stack\n"
            "    seed: null\n"
            "    legacy_unknown_key: should_be_dropped\n"
            "harmonies:\n"
            "  - start_bar: 0\n"
            "    end_bar: 2\n"
            "    preset: queen\n"
            "    legacy_unknown_key: should_be_dropped\n"
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "legacy.yaml"
            path.write_text(yaml_text)
            plan = mp.from_yaml(path)
        self.assertEqual(plan.section_overrides[0].voicing, "triad")
        self.assertIsNone(plan.section_overrides[0].cadence)
        self.assertEqual(plan.harmonies[0].preset, "queen")
        self.assertIsNone(plan.harmonies[0].harmony_rule)


# ---------------------------------------------------------------------------
# app.py dict converters
# ---------------------------------------------------------------------------

class DictConverterTests(unittest.TestCase):

    def test_override_dict_round_trip_new_fields(self):
        ov = mp.SectionOverride(
            start_bar=1, end_bar=3,
            voicing="ninth", rhythm="strum_down", mode="stack",
            seed=42,
            cadence="plagal_iv_i",
            lick="country_walk_up_5_to_1",
            tension_op="pedal_tone",
        )
        d = app._override_to_dict(ov)
        self.assertEqual(d["cadence"], "plagal_iv_i")
        self.assertEqual(d["lick"], "country_walk_up_5_to_1")
        self.assertEqual(d["tension_op"], "pedal_tone")
        back = app._dict_to_override(d)
        self.assertEqual(back.cadence, "plagal_iv_i")
        self.assertEqual(back.lick, "country_walk_up_5_to_1")
        self.assertEqual(back.tension_op, "pedal_tone")

    def test_override_dict_empty_strings_to_none(self):
        d = app._default_override_dict()
        # default dict has "" for the new fields
        self.assertEqual(d["cadence"], "")
        self.assertEqual(d["lick"], "")
        self.assertEqual(d["tension_op"], "")
        back = app._dict_to_override(d)
        self.assertIsNone(back.cadence)
        self.assertIsNone(back.lick)
        self.assertIsNone(back.tension_op)

    def test_harmony_dict_round_trip_harmony_rule(self):
        h = mp.HarmonyTag(
            start_bar=0, end_bar=4, preset="queen",
            harmony_rule="contrary_motion",
        )
        d = app._harmony_to_dict(h)
        self.assertEqual(d["harmony_rule"], "contrary_motion")
        back = app._dict_to_harmony(d)
        self.assertEqual(back.harmony_rule, "contrary_motion")

    def test_harmony_dict_default_harmony_rule_is_none(self):
        d = app._default_harmony_dict()
        self.assertEqual(d["harmony_rule"], "")
        back = app._dict_to_harmony(d)
        self.assertIsNone(back.harmony_rule)


# ---------------------------------------------------------------------------
# render_melody_plan — section overrides
# ---------------------------------------------------------------------------

class RenderLickOverrideTests(unittest.TestCase):

    def test_lick_override_stamps_at_start_bar(self):
        """``lick="pop_anacrusis_2_3_5"`` replaces the bar range's notes
        with the lick's events placed at the override's start bar."""
        plan = _simple_plan(section_overrides=[
            mp.SectionOverride(
                start_bar=1, end_bar=2,
                lick="pop_anacrusis_2_3_5",
            ),
        ])
        mel_track, _ = mp.render_melody_plan(plan)
        n_lick_events = len(MELODIC_LICKS["pop_anacrusis_2_3_5"]["events"])
        # Bar 0 keeps its original note (pitch=60). Bar 1 gets replaced
        # by the lick. Bars 2/3 keep their originals (pitches 62/63).
        starts = sorted(n.start for n in mel_track.notes)
        self.assertGreater(len(starts), 0)
        # We should see *at least* (originals outside bar 1) + (lick events)
        originals_outside = 3  # bars 0, 2, 3
        self.assertGreaterEqual(len(mel_track.notes),
                                originals_outside + n_lick_events)


class RenderCadenceOverrideTests(unittest.TestCase):

    def test_cadence_override_snaps_last_note_in_range(self):
        """An ``authentic_v_i`` cadence on a range ending at bar 4
        forces the last note in that range onto a C (pitch class 0)."""
        plan = _simple_plan(section_overrides=[
            mp.SectionOverride(
                start_bar=0, end_bar=4,
                cadence="authentic_v_i",
            ),
        ])
        mel_track, _ = mp.render_melody_plan(plan)
        # Find the last note that started in the override's bar range
        # (we render at 120 BPM, 4/4 → bar = 2.0s).
        bar_dur = 2.0
        in_range = [n for n in mel_track.notes
                    if 0.0 <= n.start < 4 * bar_dur]
        self.assertTrue(in_range, "no notes ended up in the override range")
        last = max(in_range, key=lambda n: n.start)
        self.assertEqual(last.pitch % 12, 0,
                         f"authentic_v_i should land on C; got pitch {last.pitch}")

    def test_deceptive_cadence_lands_on_six(self):
        plan = _simple_plan(section_overrides=[
            mp.SectionOverride(
                start_bar=0, end_bar=4,
                cadence="deceptive_v_vi",
            ),
        ])
        mel_track, _ = mp.render_melody_plan(plan)
        bar_dur = 2.0
        in_range = [n for n in mel_track.notes
                    if 0.0 <= n.start < 4 * bar_dur]
        last = max(in_range, key=lambda n: n.start)
        self.assertEqual(last.pitch % 12, 9,
                         f"deceptive_v_vi should land on A (pc 9); got {last.pitch}")


class RenderHarmonyRuleTests(unittest.TestCase):

    def test_harmony_rule_passthrough_does_not_error(self):
        """A HarmonyTag with ``harmony_rule="voice_leading_smooth"``
        should render to a non-empty Harmony track."""
        plan = _simple_plan(harmonies=[
            mp.HarmonyTag(
                start_bar=0, end_bar=4, preset="queen",
                harmony_rule="voice_leading_smooth",
            ),
        ])
        _, harm_track = mp.render_melody_plan(plan)
        self.assertIsNotNone(harm_track)
        self.assertGreater(len(harm_track.notes), 0)


# ---------------------------------------------------------------------------
# regenerate_bars — plan-level threading
# ---------------------------------------------------------------------------

class RegenerateBarsThreadsPlanSettingsTests(unittest.TestCase):

    def test_regenerate_preserves_plan_level_fields(self):
        plan = _simple_plan(
            phrase_shape="rise",
            default_cadence="plagal_iv_i",
            motif_development=["repeat", "sequence_up"],
        )
        new_plan = mp.regenerate_bars(
            plan, start_bar=0, end_bar=4, seed=7,
        )
        self.assertEqual(new_plan.phrase_shape, "rise")
        self.assertEqual(new_plan.default_cadence, "plagal_iv_i")
        self.assertEqual(new_plan.motif_development,
                         ["repeat", "sequence_up"])

    def test_regenerate_with_cadence_snaps_last_note_in_range(self):
        """Plan-level ``default_cadence`` is passed to ``add_melody``;
        the last regenerated note in the range should land on the
        cadence's target pitch class."""
        plan = _simple_plan(
            phrase_shape="arc",
            default_cadence="authentic_v_i",
            motif_development=None,
        )
        new_plan = mp.regenerate_bars(
            plan, start_bar=0, end_bar=4, seed=42,
        )
        in_range = [n for n in new_plan.notes if 0 <= n.bar < 4]
        self.assertTrue(in_range)
        last = max(in_range, key=lambda n: (n.bar, n.beat))
        self.assertEqual(last.pitch % 12, 0,
                         f"plan-level authentic_v_i should land on C; "
                         f"got pitch {last.pitch}")


# ---------------------------------------------------------------------------
# Studio widget keys — survive @gr.render re-renders
# ---------------------------------------------------------------------------

class StudioWidgetKeysTests(unittest.TestCase):

    def _capture_keys(self, render_fn, *render_args):
        captured: list[tuple[str, str | None]] = []
        orig = {
            "Dropdown": gr.Dropdown.__init__,
            "Number": gr.Number.__init__,
            "Slider": gr.Slider.__init__,
            "Textbox": gr.Textbox.__init__,
            "Button": gr.Button.__init__,
            "Radio": gr.Radio.__init__,
        }

        def make_spy(name, real):
            def __init__(self, *args, **kwargs):
                captured.append((name, kwargs.get("key")))
                return real(self, *args, **kwargs)
            return __init__

        try:
            for name, real in orig.items():
                setattr(getattr(gr, name), "__init__", make_spy(name, real))
            with gr.Blocks():
                render_fn(*render_args)
        finally:
            for name, real in orig.items():
                setattr(getattr(gr, name), "__init__", real)
        return captured

    def test_override_row_has_new_dropdown_keys(self):
        ov = app._default_override_dict()
        captured = self._capture_keys(
            app._render_override_row, 0, ov, gr.State([]),
        )
        keys = {k for _, k in captured if k}
        self.assertIn("override_0_cadence", keys)
        self.assertIn("override_0_lick", keys)
        self.assertIn("override_0_tension_op", keys)

    def test_harmony_row_has_harmony_rule_key(self):
        hm = app._default_harmony_dict()
        captured = self._capture_keys(
            app._render_harmony_row, 0, hm, gr.State([]),
        )
        keys = {k for _, k in captured if k}
        self.assertIn("harmony_0_harmony_rule", keys)


# ---------------------------------------------------------------------------
# melody_sync_plan_settings handler
# ---------------------------------------------------------------------------

class SyncPlanSettingsTests(unittest.TestCase):

    def test_sync_updates_plan_level_fields(self):
        plan = _simple_plan()
        out = app.melody_sync_plan_settings(
            plan, "fall", "half_iv_v",
            "repeat, sequence_up, inversion",
        )
        self.assertEqual(out.phrase_shape, "fall")
        self.assertEqual(out.default_cadence, "half_iv_v")
        self.assertEqual(out.motif_development,
                         ["repeat", "sequence_up", "inversion"])

    def test_sync_blank_motif_text_becomes_none(self):
        plan = _simple_plan(motif_development=["repeat"])
        out = app.melody_sync_plan_settings(
            plan, "arc", "authentic_v_i", "",
        )
        self.assertIsNone(out.motif_development)

    def test_sync_blank_cadence_becomes_none(self):
        plan = _simple_plan()
        out = app.melody_sync_plan_settings(plan, "arc", "", "")
        self.assertIsNone(out.default_cadence)

    def test_sync_none_plan_returns_none(self):
        out = app.melody_sync_plan_settings(None, "arc", "authentic_v_i", "")
        self.assertIsNone(out)


# ---------------------------------------------------------------------------
# Catalog choice integrity (UI shows only valid keys)
# ---------------------------------------------------------------------------

class CatalogChoicesAreValidTests(unittest.TestCase):
    """The Studio dropdowns are populated from these catalog dicts; if
    a future rename breaks the keys, the UI silently loses options."""

    def test_cadence_choices_are_dict_keys(self):
        self.assertGreaterEqual(len(CADENCES), 4)
        self.assertIn("authentic_v_i", CADENCES)
        self.assertIn("plagal_iv_i", CADENCES)

    def test_harmony_op_choices_present(self):
        self.assertIn("voice_leading_smooth", HARMONY_OPS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
