"""Tests for the TechniqueBank registry, role normalization, and the
30 built-in techniques registered at import time."""

from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path
from typing import Callable

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.composition import (
    BANK,
    Technique,
    TechniqueBank,
    TechniqueContext,
    role_for_label,
    SECTION_ROLES,
)


def _noop(midi, ctx) -> None:
    return None


class RoleNormalizationTests(unittest.TestCase):

    def test_basic_role_resolution(self):
        cases = {
            "Intro": "intro",
            "Buildup": "intro",
            "Verse 1": "verse",
            "Verse 2": "verse",
            "Pre-chorus": "verse",
            "Vamp A": "verse",
            "Groove": "verse",
            "Chorus 1": "chorus",
            "Drop 1": "chorus",
            "Hook": "chorus",
            "Lift": "chorus",
            "Bridge": "bridge",
            "Break": "bridge",
            "Solo": "bridge",
            "Outro": "outro",
            "Outro vamp": "outro",
            "Fade out": "outro",
        }
        for label, expected in cases.items():
            self.assertEqual(
                role_for_label(label), expected,
                f"{label!r} should resolve to {expected!r}",
            )

    def test_unknown_falls_back_to_verse(self):
        self.assertEqual(role_for_label("zoinks"), "verse")
        self.assertEqual(role_for_label(""), "verse")


class BankRegistrationTests(unittest.TestCase):

    def test_register_and_pick(self):
        """A custom bank with weights 1 + 3 picks the 3-weight ~75% of
        the time over a large sample."""
        b = TechniqueBank()
        t_low = Technique(
            name="t_low", label="Low", description="",
            instruments=("chords",), section_roles=("verse",),
            weight=1, apply=_noop,
        )
        t_high = Technique(
            name="t_high", label="High", description="",
            instruments=("chords",), section_roles=("verse",),
            weight=3, apply=_noop,
        )
        b.register(t_low)
        b.register(t_high)
        rng = np.random.default_rng(42)
        picks = Counter()
        for _ in range(2000):
            t = b.pick("chords", "verse", rng)
            picks[t.name] += 1
        ratio = picks["t_high"] / 2000
        self.assertGreater(ratio, 0.65)
        self.assertLess(ratio, 0.85)

    def test_pick_returns_none_when_no_match(self):
        b = TechniqueBank()
        self.assertIsNone(
            b.pick("chords", "verse", np.random.default_rng(1)),
        )

    def test_preferred_tags_doubles_weight(self):
        b = TechniqueBank()
        a = Technique(
            name="a", label="A", description="",
            instruments=("bass",), section_roles=("verse",),
            weight=1, apply=_noop,
        )
        b.register(a)
        # Add a tagged competitor with same base weight; preferred_tags
        # should make it win the majority of picks.
        tagged = Technique(
            name="b", label="B", description="",
            instruments=("bass",), section_roles=("verse",),
            weight=1, tags=("funk_rock",), apply=_noop,
        )
        b.register(tagged)
        rng = np.random.default_rng(7)
        picks = Counter()
        for _ in range(2000):
            t = b.pick("bass", "verse", rng, preferred_tags=("funk_rock",))
            picks[t.name] += 1
        self.assertGreater(picks["b"] / 2000, 0.55)

    def test_get_by_name(self):
        t = BANK.get("funk_walk")
        self.assertIsNotNone(t)
        self.assertEqual(t.name, "funk_walk")
        self.assertIn("bass", t.instruments)
        self.assertIn("verse", t.section_roles)

    def test_unknown_name_returns_none(self):
        self.assertIsNone(BANK.get("not_a_real_technique"))


class BuiltinsCoverageTests(unittest.TestCase):
    """Every (instrument, role) cell must have at least one technique
    so a random pick never falls into a hole."""

    INSTRUMENTS = ("chords", "bass", "melody", "drums")

    def test_all_cells_have_coverage(self):
        missing = []
        for inst in self.INSTRUMENTS:
            for role in SECTION_ROLES:
                if not BANK.list_for(inst, role):
                    missing.append((inst, role))
        self.assertEqual(missing, [],
                         f"Cells with no technique: {missing}")

    def test_total_bank_size_at_least_150(self):
        self.assertGreaterEqual(len(BANK.all_techniques()), 150)

    def test_each_cell_has_at_least_two_options(self):
        """For weighted-random picks to feel random, every cell should
        ship with ≥2 candidates. The Funk Rock starter set + variety
        pass should put every cell over the threshold."""
        sparse = []
        for inst in self.INSTRUMENTS:
            for role in SECTION_ROLES:
                n = len(BANK.list_for(inst, role))
                if n < 2:
                    sparse.append((inst, role, n))
        self.assertEqual(sparse, [], f"Cells with <2 candidates: {sparse}")

    def test_funk_rock_tag_present(self):
        """The funk_rock starter set ships with at least one technique
        per chord/bass/drums instrument."""
        for inst in ("chords", "bass", "drums"):
            tagged = [
                t for t in BANK.all_techniques()
                if inst in t.instruments and "funk_rock" in t.tags
            ]
            self.assertGreater(
                len(tagged), 0,
                f"No funk_rock-tagged techniques for instrument {inst!r}",
            )

    def test_all_genre_tags_have_techniques(self):
        """Every genre family we ship presets for has at least one
        technique in the bank — otherwise compose_song's preferred
        tags do nothing for that preset."""
        required = {"pop", "rock", "funk_rock", "jazz", "blues",
                    "ballad", "edm", "hip_hop", "metal",
                    "country", "reggae", "latin", "disco", "soul", "punk",
                    "bossa_jazz", "hard_bop", "modal_jazz",
                    "ballad_jazz", "bebop", "jazz_blues", "piano"}
        present = set()
        for t in BANK.all_techniques():
            present.update(t.tags)
        missing = required - present
        self.assertEqual(missing, set(),
                         f"Genre tags missing techniques: {missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
