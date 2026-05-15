"""Tests for the seven new full-song presets and auto-apply hook.

Each preset must:
- be present in ``STYLES``.
- have ``default_bars`` exactly equal to the sum of its "Full song"
  rhythm_variant section spans (each row covers ``[start, end]``
  inclusive). Catches arithmetic drift between section labels and the
  bars-slider auto-fill.
- reference only known rhythm + bass pattern names so the renderer
  doesn't silently fall through to defaults.

Plus an auto-apply assertion on ``_apply_preset``: picking a full-song
style sets ``bars`` and pre-fills ``rhythm_overrides_state`` with the
first variant's rows.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.daw_integration.generic.styles import STYLES
from src.daw_integration.generic.midi_export import STRUM_RHYTHMS


FULL_SONG_KEYS = (
    "pop_full_song",
    "rock_anthem_full",
    "funk_full_song",
    "jazz_aaba_full",
    "blues_12bar_full",
    "ballad_full",
    "edm_full_song",
    "hip_hop_full",
    "metal_full",
    "country_full",
    "reggae_full",
    "disco_full",
    "soul_motown_full",
    "jazz_bossa_full",
    "jazz_hard_bop_full",
    "jazz_modal_full",
    "jazz_ballad_full",
    "jazz_piano_full",
)

from src.daw_integration.generic.midi_export import (
    STRUM_RHYTHMS, ARPEGGIO_PATTERNS,
)

KNOWN_CHORD_RHYTHMS = (
    set(STRUM_RHYTHMS.keys())
    | set(ARPEGGIO_PATTERNS.keys())          # arpeggio_up / arpeggio_down etc
    | {"pad", "pulse_quarter", "stabs_8th"}  # auto-scale rhythms
    | {""}
)

# Mirror the BASS_PATTERNS list in app.py (the dropdown choices).
KNOWN_BASS_PATTERNS = {
    "", "root", "root_fifth", "walking", "walking_swing",
    "funk_16ths", "offbeat", "disco_octave", "palm_mute_8ths",
    "flea_slap", "geddy_lee", "bootsy_slap",
    "waltz_bass", "compound_6_8_bass",
    "tumbao", "salsa_montuno_bass", "reggaeton_dembow_bass",
    "samba_partido_alto", "arabic_iqa_baladi",
    "indian_dhol_root", "gamelan_balungan",
}


class PresetsPresentTests(unittest.TestCase):

    def test_all_seven_full_song_presets_load(self):
        for k in FULL_SONG_KEYS:
            self.assertIn(k, STYLES, f"missing full-song preset {k!r}")
            preset = STYLES[k]
            self.assertTrue(
                preset.rhythm_variants,
                f"{k} has no rhythm_variants — the full-song shape "
                "needs at least one named variant",
            )


class SectionSumTests(unittest.TestCase):
    """``default_bars`` is what the bars slider snaps to when the user
    picks this style. It MUST equal the sum of the "Full song"
    variant's row spans, otherwise the auto-filled override accordion
    runs off the end of (or under) the actual piece."""

    def test_default_bars_equals_section_sum(self):
        for k in FULL_SONG_KEYS:
            preset = STYLES[k]
            self.assertIn("Full song", preset.rhythm_variants)
            rows = preset.rhythm_variants["Full song"]
            section_sum = sum(
                int(r["end_bar"]) - int(r["start_bar"]) + 1
                for r in rows
            )
            self.assertEqual(
                preset.default_bars, section_sum,
                f"{k}: default_bars={preset.default_bars} does not match "
                f"section sum {section_sum}; rows={rows}",
            )


class KnownNamesTests(unittest.TestCase):

    def test_chord_rhythm_names_are_real(self):
        for k in FULL_SONG_KEYS:
            for v_name, rows in (STYLES[k].rhythm_variants or {}).items():
                for r in rows:
                    h1 = (r.get("chord_rhythm_h1") or "").strip()
                    h2 = (r.get("chord_rhythm_h2") or "").strip()
                    self.assertIn(h1, KNOWN_CHORD_RHYTHMS,
                                  f"{k}/{v_name}: unknown h1 {h1!r}")
                    self.assertIn(h2, KNOWN_CHORD_RHYTHMS,
                                  f"{k}/{v_name}: unknown h2 {h2!r}")

    def test_bass_pattern_names_are_real(self):
        for k in FULL_SONG_KEYS:
            for v_name, rows in (STYLES[k].rhythm_variants or {}).items():
                for r in rows:
                    bp = (r.get("bass_pattern") or "").strip()
                    self.assertIn(bp, KNOWN_BASS_PATTERNS,
                                  f"{k}/{v_name}: unknown bass_pattern {bp!r}")


class DefaultInstrumentsTests(unittest.TestCase):
    """Every preset that ships ``default_instruments`` must reference
    only valid instrument ids — otherwise picking the style auto-fills
    the family CheckboxGroups with ghost values that won't render."""

    def test_default_instruments_resolve_in_registry(self):
        from src.composition.instruments import INSTRUMENT_REGISTRY
        for k in FULL_SONG_KEYS:
            preset = STYLES[k]
            for inst_id in preset.default_instruments:
                self.assertIn(
                    inst_id, INSTRUMENT_REGISTRY,
                    f"{k}: default_instruments references unknown id "
                    f"{inst_id!r}",
                )

    def test_full_song_presets_set_default_instruments(self):
        """Each full-song preset should ship a non-empty default
        instrumentation so the family CheckboxGroups auto-fill on
        preset change."""
        for k in FULL_SONG_KEYS:
            self.assertGreater(
                len(STYLES[k].default_instruments), 0,
                f"{k}: default_instruments is empty",
            )


class PacingOptionsTests(unittest.TestCase):
    """Every preset that opts into pacing must reference names the
    pacing registry actually knows — otherwise compose_song silently
    falls back to ``uniform_1`` and the preset's intended variation
    disappears."""

    def test_pacing_options_resolve_in_registry(self):
        from src.composition.pacing import PACING_REGISTRY
        for k in FULL_SONG_KEYS:
            preset = STYLES[k]
            for name in preset.pacing_options:
                self.assertIn(
                    name, PACING_REGISTRY,
                    f"{k}: pacing_options references unknown strategy "
                    f"{name!r}",
                )
            for name in preset.bridge_pacing_options:
                self.assertIn(
                    name, PACING_REGISTRY,
                    f"{k}: bridge_pacing_options references unknown "
                    f"strategy {name!r}",
                )

    def test_full_song_presets_set_pacing_options(self):
        """All 18 full-song presets should populate pacing_options so
        the random generator actually varies harmonic rhythm."""
        for k in FULL_SONG_KEYS:
            self.assertGreater(
                len(STYLES[k].pacing_options), 0,
                f"{k}: pacing_options is empty",
            )


class DefaultBarsBackwardCompatTests(unittest.TestCase):

    def test_simple_presets_keep_default_8_bars(self):
        """Existing presets must keep default_bars=8 so picking 'pop'
        or 'funk' doesn't suddenly slam the bars slider to 128."""
        for k in ("pop", "funk", "rock", "jazz", "country", "bossa_nova"):
            if k not in STYLES:
                continue  # tolerate naming drift
            self.assertEqual(
                STYLES[k].default_bars, 8,
                f"{k}: default_bars should still be 8 (got "
                f"{STYLES[k].default_bars})",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
