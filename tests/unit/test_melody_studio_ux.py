"""Phase 3 tests for the Melody Studio UX moderate restructure.

Covers:
- ``_section_timeline_html`` produces empty-state hint when no
  overrides / harmonies; renders coloured bands when present.
- Bar percentages are clamped to [0, 100].
- Save button hierarchy: primary "Save as new block" is at the top
  level; the sidecar save lives inside an "Advanced save options" accordion.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import gradio as gr

import app


class SectionTimelineTests(unittest.TestCase):

    def test_empty_returns_hint(self):
        out = app._section_timeline_html([], [], bars=8)
        self.assertIn("No sections or harmonies yet", out)

    def test_renders_band_for_override(self):
        ov = {
            "start_bar": 2, "end_bar": 5,
            "voicing": "ninth", "rhythm": "charleston",
            "mode": "stack", "cadence": "", "lick": "", "tension_op": "",
        }
        out = app._section_timeline_html([ov], [], bars=8)
        self.assertIn("voicing=ninth", out)
        self.assertIn("rhythm=charleston", out)
        # 25% to 62.5% of an 8-bar plan.
        self.assertIn("left: 25.0%", out)
        # Section row label
        self.assertIn("Section 1", out)

    def test_renders_band_for_harmony(self):
        hm = {
            "start_bar": 0, "end_bar": 4, "preset": "queen",
            "intervals": "1,2", "harmony_rule": "voice_leading_smooth",
        }
        out = app._section_timeline_html([], [hm], bars=8)
        self.assertIn("queen", out)
        self.assertIn("1,2", out)
        self.assertIn("voice_leading_smooth", out)
        self.assertIn("Harmony 1", out)

    def test_band_percent_clamps_when_out_of_range(self):
        """An override extending past the plan's bar count should clamp
        to 100% width, not run off the strip."""
        ov = {"start_bar": 0, "end_bar": 99, "voicing": "triad"}
        out = app._section_timeline_html([ov], [], bars=8)
        # Should never produce a width > 100 or a negative width.
        # Look for the inline-style width attribute.
        import re
        widths = [float(m) for m in re.findall(r"width: ([\d.]+)%", out)]
        for w in widths:
            self.assertLessEqual(w, 100.0)
            self.assertGreaterEqual(w, 0.0)

    def test_defaults_to_8_bars_when_unset(self):
        ov = {"start_bar": 0, "end_bar": 8}
        # bars=None / 0 falls back to 8 — the band fills the full strip.
        out = app._section_timeline_html([ov], [], bars=0)
        self.assertIn("Bars 1 → 8", out)


class StudioStructureTests(unittest.TestCase):
    """Capture the widget tree for the Studio tab and assert the new
    layout shape: primary Note list at top, alternate views inside
    'Advanced views', editing inside one 'Editing' accordion, sidecar
    save inside 'Advanced save options'."""

    def _capture_accordion_labels(self) -> list[str]:
        labels: list[str] = []
        orig = gr.Accordion.__init__

        def spy(self, *args, **kwargs):
            label = kwargs.get("label")
            if label is None and args:
                label = args[0]
            labels.append(str(label))
            return orig(self, *args, **kwargs)

        try:
            gr.Accordion.__init__ = spy
            with gr.Blocks():
                # Calling build_app constructs the whole app; the Studio
                # tab is built as part of that.
                app.build_app()
        finally:
            gr.Accordion.__init__ = orig
        return labels

    def test_advanced_views_accordion_exists(self):
        labels = self._capture_accordion_labels()
        self.assertTrue(
            any("Advanced views" in l for l in labels),
            f"missing 'Advanced views' accordion; got labels {labels}",
        )

    def test_editing_accordion_exists(self):
        labels = self._capture_accordion_labels()
        self.assertTrue(
            any("Editing" in l for l in labels),
            f"missing unified 'Editing' accordion; got labels {labels}",
        )

    def test_advanced_save_options_accordion_exists(self):
        labels = self._capture_accordion_labels()
        self.assertTrue(
            any("Advanced save" in l for l in labels),
            f"missing 'Advanced save options' accordion; got labels {labels}",
        )

    def test_legacy_accordion_names_no_longer_present(self):
        """The old three sibling accordions ('Plan settings',
        'Section overrides', 'Harmonies') are gone — they're inside
        the unified Editing accordion now."""
        labels = self._capture_accordion_labels()
        # 'Plan settings' as a top-level accordion is gone. (We can't
        # discriminate top-level vs nested from this spy, so we check
        # the exact legacy strings don't appear.)
        self.assertNotIn("Plan settings", labels)
        self.assertNotIn("Section overrides", labels)
        self.assertNotIn("Harmonies", labels)


if __name__ == "__main__":
    unittest.main(verbosity=2)
