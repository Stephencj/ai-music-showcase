"""Every sampled library must allow selling and monetising the music made with
it: the licence table in data/instruments/README.md lists each library folder
sampled.py plays, and none may carry NonCommercial (NC) or NoDerivatives (ND)
terms."""

import re
import unittest
from pathlib import Path

from src.audio_processing.render.sampled import SAMPLED_INSTRUMENTS
# CC BY libraries must also have their credit line in CREDITS.md.

README = Path(__file__).resolve().parents[2] / "data" / "instruments" / "README.md"
# CC "NC"/"ND" elements (BY-NC-SA, BY-ND …) and their spelled-out forms.
FORBIDDEN = re.compile(r"(?<![A-Za-z])(NC|ND)(?![A-Za-z])|non[- ]?commercial|no[- ]?deriv", re.I)


def licence_rows() -> dict[str, str]:
    """Folder → licence, from the "| Part | Library | Folder | Licence |" table."""
    rows: dict[str, str] = {}
    in_table = False
    for line in README.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[:4] == ["Part", "Library", "Folder", "Licence"]:
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            if set(cells[0]) <= {"-", ":"}:
                continue
            rows[cells[2]] = cells[3]
    return rows


class InstrumentLicenceTest(unittest.TestCase):
    def test_no_noncommercial_or_noderivatives_licence(self):
        rows = licence_rows()
        self.assertTrue(rows, "licence table not found in data/instruments/README.md")
        bad = {folder: lic for folder, lic in rows.items() if FORBIDDEN.search(lic)}
        self.assertEqual(bad, {}, "NC/ND-licensed samples can't be used in music that's sold")

    def test_every_played_library_is_listed(self):
        listed = set(licence_rows())
        used = {Path(i.sfz).parts[0] for i in SAMPLED_INSTRUMENTS if i.sfz}
        self.assertEqual(used - listed, set(), "add these folders and their licences to the README table")

    def test_attribution_licences_are_credited(self):
        credits = (README.parents[2] / "CREDITS.md").read_text()
        for folder, lic in licence_rows().items():
            if re.search(r"\bBY\b", lic):
                quoted = re.findall(r'"([^"]+)"', lic)
                self.assertTrue(quoted, f"{folder}: give the credit line in quotes")
                for line in quoted:
                    self.assertIn(line, credits, f"{folder}: add its credit to CREDITS.md")

    def test_pattern(self):
        for lic in ("CC BY-NC-SA 4.0", "CC-BY-NC-4.0", "CC BY-ND 4.0", "Non-commercial use only", "NoDerivatives"):
            self.assertTrue(FORBIDDEN.search(lic), lic)
        for lic in ("CC0", "CC BY 3.0: credit him", "GPL 3 with FreePats' exception", "MIT"):
            self.assertFalse(FORBIDDEN.search(lic), lic)


if __name__ == "__main__":
    unittest.main()
