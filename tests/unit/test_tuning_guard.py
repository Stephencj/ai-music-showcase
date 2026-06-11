"""Tuning guard — a tripwire for 'harmony left the key'.

The recurring 'out of tune' bugs (a tritone-sub ♭II7, a borrowed-mediant ♭VI)
all shared one trait: a chord ROOTED outside the section's scale. A Roman with
an accidental prefix (``bII``, ``bVI``, ``#IV``) is exactly that — a
chromatic-root chord — while secondary dominants (``II7``, diatonic root) and
blue notes (melody, not chord roots) are not. So we measure the fraction of a
section's bars spent on chromatic-root chords and assert it stays low for the
GROUNDED genres (jazz/blues are allowed their adventurous reharm and aren't
guarded here).

This catches gross re-colouring (the 25%+ bridges that sounded wrong) while
allowing a single tasteful chromatic chord (~≤12% today).
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import src.composition.builtins  # noqa: F401  (registers the technique bank)
from src.api.arrangement import build_sections
from src.composition.song_composer import compose_song
from src.daw_integration.generic.styles import STYLES

# Harmonically grounded genres — these should stay essentially in-key.
GROUNDED = [
    "pop_full_song", "rock_anthem_full", "funk_full_song", "soul_motown_full",
    "disco_full", "country_full", "reggae_full", "hip_hop_full", "metal_full",
    "ballad_full", "edm_full_song",
]
THRESHOLD = 0.20   # max share of a section's bars on chromatic-root chords
SEEDS = 4
_CHROMATIC = re.compile(r"^[b#♭♯]")


def _worst_section(genre, sections, prog):
    """(fraction, label) of the most chromatic section in one realized song."""
    worst, where = 0.0, ""
    for s in sections:
        bars = chrom = 0.0
        for p in prog:
            if s["start_bar"] <= float(p["start_bar"]) < s["end_bar"] + 1:
                dur = float(p["end_bar"]) - float(p["start_bar"])
                bars += dur
                if _CHROMATIC.match(str(p["symbol"])):
                    chrom += dur
        f = chrom / bars if bars else 0.0
        if f > worst:
            worst, where = f, s["label"]
    return worst, where


def _compose(genre, section_presets=None, seed=0, key="C"):
    secs = build_sections(genre, [], section_presets)
    out = compose_song(
        genre=genre, sections=secs, seed=seed, key=key,
        enabled_instruments=tuple(STYLES[genre].default_instruments)
        or ("drum_kit", "electric_bass", "piano"),
        output_dir=Path(tempfile.mkdtemp()), skip_audio=True)
    return secs, out["progression"]


class TuningGuardTests(unittest.TestCase):
    def test_grounded_genres_stay_in_key(self):
        offenders = []
        for g in GROUNDED:
            for seed in range(SEEDS):
                secs, prog = _compose(g, seed=seed)
                f, where = _worst_section(g, secs, prog)
                if f > THRESHOLD:
                    offenders.append(f"{g}/{where} seed{seed}: {f*100:.0f}% chromatic-root")
        self.assertFalse(
            offenders,
            "Sections drifted out of key (chromatic-root chords over the "
            f"{THRESHOLD*100:.0f}% guard):\n  " + "\n  ".join(offenders))

    def test_multi_preset_mixes_stay_in_key(self):
        # The original out-of-tune reports were multi-preset songs. A grounded
        # song with funk/rock/soul/dance sections must still stay in-key.
        combos = [
            {"verse": "funk", "prechorus": "rock", "bridge": "soul_motown_full", "breakdown": "dance"},
            {"verse": "soul_motown_full", "chorus": "disco", "bridge": "funk"},
            {"chorus": "rock", "bridge": "country"},
        ]
        offenders = []
        for sp in combos:
            for seed in range(2):
                secs, prog = _compose("pop_full_song", section_presets=sp, seed=seed)
                f, where = _worst_section("pop_full_song", secs, prog)
                if f > THRESHOLD:
                    offenders.append(f"{sp}/{where} seed{seed}: {f*100:.0f}%")
        self.assertFalse(
            offenders, "Multi-preset sections drifted out of key:\n  " + "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main()
