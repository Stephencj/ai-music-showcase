# Carol lyric sources

The sung carols' words live in `data/lyrics/<carol>.txt`, one file per carol,
downloaded by `scripts/setup/fetch_carol_lyrics.py` from public-domain
editions on Wikisource. Every text below was published before 1929, so it is
in the public domain in the US. The code never contains the words: it reads
these files, splits the lines into syllables and lines them up with the
melodies in `src/composition/carols.py` (`src/composition/lyrics.py`).

To refresh the files: `python scripts/setup/fetch_carol_lyrics.py` (it prints
only counts). The file format is described in `src/composition/lyrics.py`.

| Carol | Source | Why it is public domain |
|---|---|---|
| `silent_night` | https://en.wikisource.org/wiki/The_Army_and_Navy_Hymnal/Hymns/Silent_Night,_Holy_Night | Joseph Mohr's carol in English as printed in The Army and Navy Hymnal (1920); the hymnal credits verse 1 to John Freeman Young's 1859 translation. |
| `jingle_bells` | https://en.wikisource.org/wiki/Jingle_Bells | James Lord Pierpont, "One Horse Open Sleigh" (1857). |
| `deck_the_halls` | https://en.wikisource.org/wiki/Deck_the_Halls | English words by Thomas Oliphant (1862). |
| `good_king_wenceslas` | https://en.wikisource.org/wiki/Good_King_Wenceslas_(1904) | John Mason Neale, first published in Carols for Christmas-tide (1853); this printing is the 1904 illustrated edition. |
| `joy_to_the_world` | https://en.wikisource.org/wiki/The_Army_and_Navy_Hymnal/Hymns/Joy_to_the_World!_the_Lord_Is_Come | Isaac Watts (1719), as printed in The Army and Navy Hymnal (1920). |
| `what_child_is_this` | https://en.wikisource.org/wiki/What_Child_Is_This%3F | William Chatterton Dix (1865). |
| `the_first_noel` | https://en.wikisource.org/wiki/The_First_Nowell | Traditional English carol, published by William Sandys (1833). |

Carols without lyric files (their backing tracks carry chords only):

- `carol_of_the_bells`: instrumental. Leontovych's 1916 melody is public
  domain, but the familiar English words (1936) are not.
- `angels_we_have_heard`: James Chadwick's 1862 English text is public domain,
  but no clean edition of it was found on Wikisource to fetch.
