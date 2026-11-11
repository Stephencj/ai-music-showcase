"""Public-domain Thanksgiving hymn tunes, encoded as note data.

Same text format as the carols (src/composition/carols.py, ``TuneBook``):
written in C major, ``NOTE:beats`` melody tokens with the pickup first,
``SYMBOL:beats`` roman-numeral chords from the first downbeat.

Every tune here is in the US public domain: melody (and, for reference,
the usual words) published before 1929. The MELODIES were transcribed from
public-domain engravings and checked against each other:

- KREMSER ("We Gather Together"): the Open Hymnal Project's public-domain
  score (openhymnal.org, "We_Gather_Together-Kremser.abc", melody of the 1877
  Kremser setting, as in The Hymnal 1940) — melody from Adrianus Valerius,
  Nederlandtsche Gedenck-clanck, 1626.
- ST. GEORGE'S WINDSOR, DIX, NUN DANKET, LASST UNS ERFREUEN: the
  public-domain LilyPond scores on their English Wikipedia articles.
- SIMPLE GIFTS: Joseph Brackett's 1848 Shaker tune (the traditional session
  transcription, thesession.org tune 8033), checked note by note against the
  sung text.

The HARMONY under each melody is our own (roman numerals written for this
project, tested so every strong-beat melody note sits on its chord); no
hymnal's harmonization is copied. These tunes play as instrumentals.
"""

from __future__ import annotations

from typing import Optional

from .carols import Tune, TuneBook

_RAW: dict[str, dict] = {
    "we_gather_together": dict(
        title="We Gather Together",
        source="Tune KREMSER: Netherlands folk melody (Adrianus Valerius, Nederlandtsche Gedenck-clanck, 1626), "
               "setting Eduard Kremser 1877; English text Theodore Baker 1894. Public domain.",
        beats=3, pickup=1, scale="major", tempo=(80, 104),
        melody="G4:1 | G4:1.5 A4:.5 G4:1 | E4:1 F4:1 G4:1 | F4:1.5 E4:.5 D4:1 | E4:1 C4:1 G4:1 | "
               "G4:1.5 A4:.5 B4:1 | C5:1.5 D5:.5 B4:1 | A4:1.5 G4:.5 A4:1 | G4:2 G4:1 | "
               "G4:1.5 A4:.5 B4:1 | C5:1 G4:1 G4:1 | G4:1.5 A4:.5 F4:.5 G4:.5 | E4:1 C4:1 C4:1 | "
               "F4:1.5 G4:.5 A4:.5 F4:.5 | G4:1.5 F4:.5 E4:.5 E4:.5 | F4:1 D4:1.5 C4:.5 | C4:3",
        chords="I:3 | I:3 | ii:2 V7:1 | I:3 | V:3 | vi:2 V:1 | II7:3 | V:3 | V:3 | I:3 | IV:2 V7:1 | I:3 | "
               "IV:3 | V7:3 | IV:1 V7:2 | I:3",
    ),
    "come_ye_thankful_people": dict(
        title="Come, Ye Thankful People, Come",
        source="Tune ST. GEORGE'S WINDSOR, George J. Elvey 1858; text Henry Alford 1844. Public domain.",
        beats=4, pickup=0, scale="major", tempo=(84, 110),
        melody="E4:1.5 E4:.5 G4:1 E4:1 | C4:1 D4:1 E4:2 | E4:1.5 E4:.5 G4:1 E4:1 | C4:1 D4:1 E4:2 | "
               "E4:1.5 E4:.5 F4:1 F4:1 | D4:1.5 D4:.5 E4:2 | E4:1 F#4:1 G4:1 C4:1 | B3:1 A3:1 G3:2 | "
               "B3:1.5 B3:.5 D4:1 B3:1 | C4:1 D4:1 E4:2 | E4:1.5 E4:.5 G4:1 E4:1 | F4:1 G4:1 A4:2 | "
               "A4:1.5 A4:.5 F4:1 D4:1 | G4:1.5 G4:.5 E4:2 | F4:1 A4:1 G4:1 C4:1 | E4:1 D4:1 C4:2",
        chords="I:4 | I:1 V:1 I:2 | I:4 | vi:1 ii:1 III:2 | vi:2 ii:2 | V:2 I:2 | I:1 II7:1 V:1 IV:1 | "
               "V:1 II7:1 V:2 | V:4 | I:1 V:1 I:2 | I:4 | IV:1 V:1 vi:2 | IV:2 ii:2 | V:2 I:2 | "
               "IV:2 V:1 I:1 | I:1 V7:1 I:2",
    ),
    "for_the_beauty_of_the_earth": dict(
        title="For the Beauty of the Earth",
        source="Tune DIX, Conrad Kocher 1838, adapted W. H. Monk 1861; text Folliott S. Pierpoint 1864. "
               "Public domain.",
        beats=4, pickup=0, scale="major", tempo=(84, 108),
        melody="C5:1 B4:.5 C5:.5 D5:1 C5:1 | F5:1 F5:1 E5:2 | A4:1 B4:1 C5:1 A4:1 | G4:1 G4:1 G4:2 | "
               "C5:1 B4:.5 C5:.5 D5:1 C5:1 | F5:1 F5:1 E5:2 | A4:1 B4:1 C5:1 A4:1 | G4:1 G4:1 G4:2 | "
               "E5:1 D5:1 C5:1 E5:1 | G5:1.5 F5:.5 E5:2 | A4:1 B4:1 C5:1 F5:1 | E5:1 D5:1 C5:2",
        chords="I:2 V:1 I:1 | IV:2 I:2 | IV:1 V:1 I:1 IV:1 | V:2 I:2 | I:2 V:1 I:1 | IV:2 I:2 | "
               "IV:1 V:1 I:1 IV:1 | V:2 I:2 | I:1 V:1 I:2 | V7:2 I:2 | IV:1 V:1 I:1 ii:1 | I:1 V:1 I:2",
    ),
    "now_thank_we_all_our_god": dict(
        title="Now Thank We All Our God",
        source="Tune NUN DANKET, Johann Crüger 1647; text Martin Rinkart c. 1636, translated Catherine "
               "Winkworth 1858. Public domain.",
        beats=4, pickup=1, scale="major", tempo=(72, 96),
        melody="G4:1 | G4:1 G4:1 A4:1 A4:1 | G4:3 E4:1 | F4:1 E4:1 D4:1 E4:.5 F4:.5 | D4:2 C4:1 G4:1 | "
               "G4:1 G4:1 A4:1 A4:1 | G4:3 E4:1 | F4:1 E4:1 D4:1 E4:.5 F4:.5 | D4:2 C4:1 D4:1 | "
               "D4:1 D4:1 E4:1 E4:1 | D4:3 D4:1 | E4:.5 F#4:.5 G4:1 G4:1 F#4:1 | G4:3 G4:1 | "
               "A4:1 G4:1 F4:1 E4:1 | F4:3 E4:1 | D4:1 E4:.5 F4:.5 D4:1.5 C4:.5 | C4:4",
        chords="I:2 IV:2 | I:4 | IV:1 I:1 V:1 I:1 | V:2 I:2 | I:2 IV:2 | I:4 | IV:1 I:1 V:1 I:1 | V:2 I:2 | "
               "V:2 vi:2 | V:4 | II7:1 V:2 II7:1 | V:4 | IV:1 I:1 ii:1 I:1 | IV:3 I:1 | ii:2 V7:2 | I:4",
    ),
    "all_creatures_of_our_god": dict(
        title="All Creatures of Our God and King",
        source="Tune LASST UNS ERFREUEN, Geistliche Kirchengesäng (Cologne) 1623, as arranged by Ralph Vaughan "
               "Williams in The English Hymnal 1906; text after St Francis, translated William H. Draper "
               "c. 1919. Public domain. Written here with the half note as the beat.",
        beats=3, pickup=1, scale="major", tempo=(76, 96),
        melody="C4:1 | C4:.5 D4:.5 E4:.5 C4:.5 E4:.5 F4:.5 | G4:2 C4:1 | C4:.5 D4:.5 E4:.5 C4:.5 E4:.5 F4:.5 | "
               "G4:2 C5:.5 B4:.5 | A4:1 G4:1 C5:.5 B4:.5 | A4:1 G4:1 C5:1 | "
               "C5:.5 G4:.5 G4:.5 F4:.5 E4:.5 F4:.5 | G4:2 C5:1 | C5:.5 G4:.5 G4:.5 F4:.5 E4:.5 F4:.5 | "
               "G4:2 F4:.5 E4:.5 | D4:1 C4:1 F4:.5 E4:.5 | D4:1 C4:1 C5:.5 B4:.5 | A4:1 G4:1 C5:.5 B4:.5 | "
               "A4:1 G4:1 F4:.5 E4:.5 | D4:3 | C4:3",
        chords="I:3 | V:2 I:1 | I:3 | V:2 I:1 | IV:1 I:2 | IV:1 V:1 I:1 | I:3 | V:2 I:1 | I:3 | V:2 IV:1 | "
               "ii:1 I:1 IV:1 | V:1 vi:1 I:1 | IV:1 I:2 | IV:1 I:1 IV:1 | V7:3 | I:3",
    ),
    "simple_gifts": dict(
        title="Simple Gifts",
        source="Shaker song by Joseph Brackett, 1848 (words and tune). Public domain.",
        beats=4, pickup=1, scale="major", tempo=(84, 112),
        melody="G4:1 | C5:1 C5:.5 D5:.5 E5:.5 C5:.5 E5:.5 F5:.5 | G5:1 G5:.5 F5:.5 E5:1 D5:.5 C5:.5 | "
               "D5:1 D5:.5 C5:.5 D5:1 D5:.5 C5:.5 | D5:.5 E5:.5 D5:.5 B4:.5 G4:1 G4:1 | "
               "C5:.5 B4:.5 C5:.5 D5:.5 E5:.5 C5:.5 E5:.5 F5:.5 | G5:1 G5:.5 F5:.5 E5:1 D5:.5 C5:.5 | "
               "D5:1 D5:.5 C5:.5 D5:.5 E5:1 D5:.5 | C5:1 A4:.5 G4:.5 C5:2 | "
               "G5:2 E5:1 E5:.5 D5:.5 | E5:.5 F5:.5 E5:.5 D5:.5 C5:1 C5:.5 D5:.5 | "
               "E5:.5 C5:.5 E5:.5 F5:.5 G5:1 F5:.5 E5:.5 | D5:1 D5:.5 E5:.5 D5:1 G4:1 | "
               "C5:.5 B4:.5 C5:.5 D5:.5 E5:.5 C5:.5 E5:.5 F5:.5 | G5:1 G5:.5 F5:.5 E5:1 D5:.5 C5:.5 | "
               "D5:1 D5:.5 C5:.5 D5:.5 E5:1 D5:.5 | C5:1 A4:.5 G4:.5 C5:2",
        chords="I:4 | I:4 | V:4 | V:4 | I:4 | I:4 | V:2 I:2 | IV:1 V:1 I:2 | I:4 | I:4 | I:2 V7:2 | V:4 | "
               "I:4 | I:4 | V:2 I:2 | IV:1 V:1 I:2",
    ),
}

BOOK = TuneBook(_RAW)
HYMNS: tuple[str, ...] = BOOK.ids


def hymn(tune_id: str) -> Optional[Tune]:
    """The hymn ``tune_id`` (also accepts its title, any case), or None."""
    return BOOK.get(tune_id)


def hymn_catalog() -> dict[str, dict]:
    return BOOK.catalog()


def raw_text(tune_id: str) -> dict:
    return BOOK.raw_text(tune_id)
