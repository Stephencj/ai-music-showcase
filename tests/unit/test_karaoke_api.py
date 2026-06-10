"""Tests for the karaoke data transformation (notes + word timings)."""
import re
import unittest

from src.models.vocals.lyrics import align_words_to_notes, monophonic_line


def _karaoke_words(lyrics, notes):
    """Mirror service.karaoke_data's lyric handling: strip [Section] headers,
    align to notes, derive each word's end from its note durations."""
    sung = "\n".join(ln for ln in lyrics.splitlines()
                     if not re.match(r"^\s*\[.*\]\s*$", ln))
    out = []
    for seg in align_words_to_notes(sung, monophonic_line(notes)):
        start = float(seg["start"])
        dur = sum(float(d) for (_p, d) in seg["notes"])
        out.append({"text": seg["text"], "start": round(start, 4),
                    "end": round(start + dur, 4)})
    return out


class TestKaraokeTransform(unittest.TestCase):
    def setUp(self):
        # 6 quarter notes, one per beat at 1s spacing.
        self.notes = [(67, i, i + 0.9) for i in range(6)]

    def test_section_headers_stripped(self):
        lyrics = "[Verse 1]\none two three\n[Chorus]\nfour five six"
        words = _karaoke_words(lyrics, self.notes)
        texts = [w["text"] for w in words]
        self.assertNotIn("Verse", texts)
        self.assertNotIn("Chorus", texts)
        self.assertEqual(texts[:3], ["one", "two", "three"])

    def test_word_timings_ordered_and_bounded(self):
        words = _karaoke_words("one two three four five six", self.notes)
        self.assertTrue(words)
        for w in words:
            self.assertLess(w["start"], w["end"])           # non-empty span
        starts = [w["start"] for w in words]
        self.assertEqual(starts, sorted(starts))            # time-ordered

    def test_monophonic_line_no_overlap(self):
        overlapping = [(60, 0.0, 2.0), (64, 1.0, 3.0), (67, 2.5, 4.0)]
        line = monophonic_line(overlapping)
        for i in range(len(line) - 1):
            self.assertLessEqual(line[i][2], line[i + 1][1] + 1e-6)  # end <= next start

    def test_empty_lyrics_ok(self):
        self.assertEqual(_karaoke_words("", self.notes), [])
        self.assertEqual(_karaoke_words("[Intro]\n[Outro]", self.notes), [])


if __name__ == "__main__":
    unittest.main()
