#!/usr/bin/env python3
"""Download the carols' public-domain lyric texts into data/lyrics/.

Each carol in src/composition/carols.py that is sung gets one file,
``data/lyrics/<carol>.txt``, fetched from a public-domain edition on
Wikisource (the source page and the reason the text is public domain are in
``SOURCES`` below and in data/lyrics/SOURCES.md). The script never prints the
text: it reports the source, the stanza and line counts and the syllables
per line (what the melody alignment uses), so the files can be checked
without reading them out.

    python scripts/setup/fetch_carol_lyrics.py              # every carol
    python scripts/setup/fetch_carol_lyrics.py silent_night  # one carol
    python scripts/setup/fetch_carol_lyrics.py --check       # counts of the files already there

File format: see src/composition/lyrics.py.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

API = "https://en.wikisource.org/w/api.php"
UA = "ai-music-carol-fetch/1.0 (https://github.com/Stephencj/ai-music; personal project)"

# carol id -> where its text comes from and why it is public domain.
# ``min_lines``: ignore shorter blocks (headings, captions); ``stanzas``:
# keep only the first N verses.
SOURCES: dict[str, dict] = {
    "silent_night": {
        "page": "The Army and Navy Hymnal/Hymns/Silent Night, Holy Night",
        "why": "Joseph Mohr's carol in English as printed in The Army and Navy Hymnal (1920), whose notes credit "
               "verse 1 to John Freeman Young's 1859 translation. Published before 1929, so public domain in "
               "the US.",
    },
    "jingle_bells": {
        "page": "Jingle Bells",
        "why": "James Lord Pierpont, 'One Horse Open Sleigh' (1857). Public domain.",
    },
    "deck_the_halls": {
        "page": "Deck the Halls",
        "why": "English words by Thomas Oliphant (1862). Public domain.",
    },
    "good_king_wenceslas": {
        "page": "Good King Wenceslas (1904)",
        "why": "John Mason Neale (first published in Carols for Christmas-tide, 1853); this printing is the "
               "1904 illustrated edition. Public domain.",
        "min_lines": 8,
    },
    "joy_to_the_world": {
        "page": "The Army and Navy Hymnal/Hymns/Joy to the World! the Lord Is Come",
        "why": "Isaac Watts (1719); this printing is The Army and Navy Hymnal (1920). Public domain.",
    },
    "what_child_is_this": {
        "page": "What Child Is This?",
        "why": "William Chatterton Dix (1865). Public domain.",
    },
    "the_first_noel": {
        "page": "The First Nowell",
        "why": "Traditional English carol, as published by William Sandys (1833). Public domain.",
    },
}
# Carols without a sung text here: Carol of the Bells is instrumental (its
# familiar English words are a later, copyrighted lyric); Angels We Have
# Heard on High has no clean public-domain edition on Wikisource.
NO_TEXT = {
    "carol_of_the_bells": "Instrumental only: the familiar English words (1936) are not public domain.",
    "angels_we_have_heard": "No clean public-domain edition of James Chadwick's 1862 text was found to fetch; "
                            "the backing track ships with chords only.",
}

_NOISE = (".ws-header", ".ws-noexport", ".licenseContainer", "style", "script", "figure", ".mw-ext-score",
          ".mw-ext-score-disabled", "sup.reference", ".reference", ".mw-editsection", ".pagenum", ".ws-pagenum",
          ".wst-header-structure", "table.licenseContainer", ".similar", ".subNote", "span.wst-gap", "img",
          ".wst-nop", ".__nop", ".prp-page-image")


def page_url(title: str) -> str:
    return "https://en.wikisource.org/wiki/" + title.replace(" ", "_")


def fetch_html(title: str) -> str:
    import requests
    last = None
    for i in range(5):
        r = requests.get(API, params={"action": "parse", "page": title, "prop": "text", "format": "json",
                                      "redirects": 1}, headers={"User-Agent": UA}, timeout=30)
        if r.status_code == 200 and r.text.startswith("{"):
            data = r.json()
            if "error" in data:
                raise RuntimeError(f"{title}: {data['error'].get('code')}")
            return data["parse"]["text"]["*"]
        last = r.status_code
        time.sleep(8 * (i + 1))
    raise RuntimeError(f"{title}: HTTP {last}")


def extract(html: str) -> list[list[str]]:
    """Stanzas (lists of lines) of the verse on a Wikisource page."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".mw-parser-output") or soup
    for sel in _NOISE:
        for el in root.select(sel):
            el.decompose()
    from bs4 import NavigableString
    blocks = root.select("div.poem") or [root]
    stanzas: list[list[str]] = []
    for b in blocks:
        # HTML whitespace is not a line break; <br> is, and an empty line
        # (two <br>s, or a new paragraph) ends a stanza. Italic lines are a
        # refrain (marked with \x01 so they can be split off).
        for t in list(b.find_all(string=True)):
            if isinstance(t, NavigableString):
                t.replace_with(re.sub(r"\s+", " ", str(t)))
        for i in b.find_all(["i", "em"]):
            i.insert_before("\x01")
        for br in b.find_all("br"):
            br.replace_with("\n")
        for p in b.find_all(["p", "div", "dd", "li"]):
            p.insert_before("\n\n")
            p.insert_after("\n\n")
        text = b.get_text()
        for chunk in re.split(r"\n\s*\n", text):
            lines = [ln for ln in (clean(x) for x in chunk.splitlines()) if ln]
            if lines:
                stanzas.append(lines)
    return stanzas


def clean(line: str) -> str:
    """One line, tidied; a line set in italics keeps a leading \\x01."""
    head = line.split("\x01", 1)[0]
    italic = "\x01" in line and not re.search(r"[A-Za-z]", head)
    s = line.replace("\u00a0", " ").replace("\x01", "").strip()
    s = re.sub(r"^\(?\d{1,2}[.)]?\s+", "", s)            # stanza numbers
    s = re.sub(r"\s+", " ", s)
    if not re.search(r"[A-Za-z]", s):
        return ""
    return ("\x01" if italic else "") + s


def is_label(line: str) -> bool:
    return bool(re.fullmatch(r"(refrain|chorus|ref\.?)[:.]?", line.strip("\x01 ").lower()))


def to_file(carol: str, stanzas: list[list[str]], src: dict) -> str:
    """The data file: comments, then the stanzas. The refrain (a stanza
    labelled Refrain/Chorus, or the italic lines) is written once, as its
    own [refrain] stanza; repeats of it after later verses are dropped."""
    out = [f"# {carol}: public-domain text, fetched by scripts/setup/fetch_carol_lyrics.py",
           f"# source: {page_url(src['page'])}",
           f"# public domain: {src['why']}", ""]
    keep = int(src.get("stanzas", 0)) or len(stanzas)
    from src.composition.lyrics import line_syllables
    # Not verse: prose (a "line" far longer than a sung line), headings and
    # captions (shorter than a stanza), and a closing "Amen".
    stanzas = [[ln for ln in st if not re.fullmatch(r"\x01?a-?men[.!]?", ln.strip().lower())] for st in stanzas]
    stanzas = [st for st in stanzas if st and all(len(line_syllables(ln)) <= 16 for ln in st)
               and (len(st) >= int(src.get("min_lines", 2)) or all(ln.startswith("\x01") for ln in st)
                    or any(is_label(ln) for ln in st))]
    verses: list[list[str]] = []
    refrain: list[str] = []
    for st in stanzas:
        labelled = any(is_label(ln) for ln in st)
        body = [ln for ln in st if not is_label(ln)]
        ital = [ln[1:] for ln in body if ln.startswith("\x01")]
        plain = [ln for ln in body if not ln.startswith("\x01")]
        if labelled or (ital and not plain):
            refrain = refrain or [ln.lstrip("\x01") for ln in body]
            continue
        if ital and not refrain:
            refrain = ital
        if plain:
            verses.append(plain)
    for v in verses[:keep]:
        out += v + [""]
    if refrain:
        out += ["[refrain]"] + refrain + [""]
    return "\n".join(out).rstrip() + "\n"


def report(carol: str, path: Path) -> None:
    from src.composition import lyrics as L
    from src.composition.carols import carol as get_carol
    lyr = L.parse(path.read_text(encoding="utf-8"), carol, path)
    src = next((ln[len("# source: "):] for ln in lyr.text_lines if ln.startswith("# source: ")), "?")
    print(f"{carol}: {src}")
    for k, st in enumerate(lyr.stanzas):
        counts = [len(lyr.syllables(ln)) for ln in st.lines]
        print(f"  {'refrain' if st.refrain else f'stanza {k + 1}'}: {len(st.lines)} lines, syllables {counts}")
    tune = get_carol(carol)
    if tune and lyr.verses:
        print(f"  melody notes per pass: {len(tune.melody)}")
        for p, al in enumerate(L.align_passes(tune, lyr)):
            print(f"  pass {p + 1}: lines {len(al)}, notes/line {[a.notes[1] - a.notes[0] for a in al]}, "
                  f"melismas {sum(a.melismas for a in al)}, splits {sum(a.splits for a in al)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("carols", nargs="*", help="carol ids (default: every carol with a source)")
    ap.add_argument("--check", action="store_true", help="only report counts of the existing files")
    args = ap.parse_args()
    from src.composition.lyrics import LYRICS_DIR
    LYRICS_DIR.mkdir(parents=True, exist_ok=True)
    ids = args.carols or list(SOURCES)
    failed = []
    for cid in ids:
        if cid in NO_TEXT:
            print(f"{cid}: no text ({NO_TEXT[cid]})")
            continue
        if cid not in SOURCES:
            print(f"{cid}: unknown carol (sources: {', '.join(SOURCES)})")
            failed.append(cid)
            continue
        path = LYRICS_DIR / f"{cid}.txt"
        if not args.check:
            try:
                stanzas = extract(fetch_html(SOURCES[cid]["page"]))
            except Exception as exc:  # noqa: BLE001 — report and carry on (chords-only for that carol)
                print(f"{cid}: fetch failed ({exc}); its backing track ships chords only")
                failed.append(cid)
                continue
            if not stanzas:
                print(f"{cid}: no verse found on the page; chords only")
                failed.append(cid)
                continue
            path.write_text(to_file(cid, stanzas, SOURCES[cid]), encoding="utf-8")
            time.sleep(3)
        if path.is_file():
            report(cid, path)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
