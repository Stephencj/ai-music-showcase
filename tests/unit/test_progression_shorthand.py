"""Tests for the new ``[X Y Z] xN`` + ``Symbol xN`` progression shorthand.

The expander runs in front of the existing colon-paced / sub-bar
tokenizer so the new forms compose with everything that already
worked. Precedence:

  1. Brackets first (recursive for nesting).
  2. Bare-symbol repeats — negative lookbehind on `:` keeps paced
     tokens intact.
  3. Fall through to the existing tokenizer.

Tests below cover each layer end-to-end via ``_parse_progression_text``
plus the preprocessor in isolation.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import _expand_progression_shorthand, _parse_progression_text


class BackwardCompatTests(unittest.TestCase):
    """Existing syntaxes must parse exactly as before."""

    def test_legacy_bare_symbols(self):
        self.assertEqual(
            _parse_progression_text("I V vi IV"),
            [("I", 1.0), ("V", 1.0), ("vi", 1.0), ("IV", 1.0)],
        )

    def test_paced_unchanged(self):
        self.assertEqual(
            _parse_progression_text("I:2 V:1 vi:1 IV:4"),
            [("I", 2.0), ("V", 1.0), ("vi", 1.0), ("IV", 4.0)],
        )

    def test_sub_bar_unchanged(self):
        out = _parse_progression_text("i:.5 VII:.5 VI:.5 VII:.5")
        self.assertEqual(out, [("i", 0.5), ("VII", 0.5),
                                ("VI", 0.5), ("VII", 0.5)])

    def test_paced_not_eaten_by_symbol_repeat(self):
        """``I:2 V:1`` must NOT be misread as a `Symbol xN` form just
        because it has digits — the negative-lookbehind on `:` is the
        guardrail. Critical regression to catch."""
        out = _parse_progression_text("I:2 V:1")
        self.assertEqual(out, [("I", 2.0), ("V", 1.0)])


class BracketRepeatTests(unittest.TestCase):

    def test_simple_bracket_repeat(self):
        self.assertEqual(
            _parse_progression_text("[ii V I] x2"),
            [("ii", 1.0), ("V", 1.0), ("I", 1.0)] * 2,
        )

    def test_bracket_with_paced_tokens(self):
        """Paced tokens inside brackets keep their durations after
        the expander runs."""
        self.assertEqual(
            _parse_progression_text("[I:2 V:1] x2"),
            [("I", 2.0), ("V", 1.0), ("I", 2.0), ("V", 1.0)],
        )

    def test_multiple_brackets(self):
        self.assertEqual(
            _parse_progression_text("[I V] x2 [vi IV] x2"),
            [("I", 1.0), ("V", 1.0)] * 2 + [("vi", 1.0), ("IV", 1.0)] * 2,
        )

    def test_nested_brackets(self):
        out = _parse_progression_text("[I [V vi] x2 IV] x2")
        # Inner [V vi] x2 → V vi V vi; outer wraps × 2.
        self.assertEqual(
            out,
            [("I", 1.0), ("V", 1.0), ("vi", 1.0), ("V", 1.0),
             ("vi", 1.0), ("IV", 1.0)] * 2,
        )

    def test_uppercase_X_also_works(self):
        self.assertEqual(
            _parse_progression_text("[I V] X2"),
            [("I", 1.0), ("V", 1.0)] * 2,
        )

    def test_unclosed_bracket_passes_through(self):
        """Malformed bracket shouldn't crash; the downstream tokenizer
        emits whatever's left as a (probably-nonsense) symbol token."""
        out = _parse_progression_text("[I V")
        self.assertEqual(out, [("[I", 1.0), ("V", 1.0)])


class SymbolRepeatTests(unittest.TestCase):

    def test_single_symbol_repeat(self):
        self.assertEqual(
            _parse_progression_text("I x4"),
            [("I", 1.0)] * 4,
        )

    def test_vamp_style(self):
        """Funk vamp: ``i7 x8`` reads as 8 bars of the i7 chord."""
        self.assertEqual(
            _parse_progression_text("i7 x8"),
            [("i7", 1.0)] * 8,
        )

    def test_mixed_repeat_and_bare(self):
        self.assertEqual(
            _parse_progression_text("I x4 IV x4"),
            [("I", 1.0)] * 4 + [("IV", 1.0)] * 4,
        )


class ExpanderUnitTests(unittest.TestCase):
    """Direct assertions on the preprocessor's output text — useful
    when debugging precedence."""

    def test_brackets_expand_to_repeated_inner(self):
        out = _expand_progression_shorthand("[ii V I] x2")
        # Collapse whitespace for assertion.
        tokens = out.split()
        self.assertEqual(tokens, ["ii", "V", "I", "ii", "V", "I"])

    def test_symbol_xN_expands(self):
        out = _expand_progression_shorthand("I x3")
        self.assertEqual(out.split(), ["I", "I", "I"])

    def test_paced_not_touched_by_symbol_expander(self):
        out = _expand_progression_shorthand("I:0.5 V:0.5")
        self.assertEqual(out.split(), ["I:0.5", "V:0.5"])

    def test_idempotent_when_no_shorthand(self):
        for src in ("I V vi IV", "I:2 V:1", ""):
            self.assertEqual(
                _expand_progression_shorthand(src).strip(),
                src.strip(),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
