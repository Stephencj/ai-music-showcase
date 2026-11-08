# Sampled instruments

`sound="sampled"` renders (the default for **Jazz Fusion (Full song)**) play
tracks through real recorded instruments in SFZ format, using the player in
`src/audio_processing/render/sfz.py`. Each library is mapped to General MIDI
programs in `src/audio_processing/render/sampled.py`; a track with no
installed library renders through the soundfont as before.

Override the folder with `$AI_MUSIC_INSTRUMENTS`.

## Install

From this folder:

```bash
for r in karoryfer.black-and-blue-basses virtuosity_drums karoryfer.weresax; do
  git clone --depth 1 https://github.com/sfzinstruments/$r.git && rm -rf $r/.git
done
```

Horns (trumpet and trombone from VSCO 2 CE, CC0; ~200 MB). The library ships
WAVs without SFZ maps, so generate them after downloading:

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/sgossner/VSCO-2-CE.git vsco2-ce
(cd vsco2-ce && git sparse-checkout set "Brass/Trumpet" "Brass/Tenor Trombone") && rm -rf vsco2-ce/.git
python ../../scripts/setup/make_brass_sfz.py vsco2-ce
```

Electric guitar (lead voice "guitar"): use the **release zip**, not a git
clone — the repo's `.gitattributes` converts line endings and corrupts the WAVs:

```bash
curl -L -o bng.zip https://github.com/sfzinstruments/karoryfer.black-and-green-guitars/releases/download/v1.000/Karoryfer_Black_And_Green_Guitars_1000.zip
mkdir karoryfer.black-and-green-guitars && unzip -q bng.zip -d karoryfer.black-and-green-guitars && rm bng.zip
```

Christmas instruments (all CC0, about 1.4 GB): a grand piano, harp,
glockenspiel, sleigh bells and shaker from VCSL; flute, clarinet, oboe and a
quiet pipe organ from VSCO 2 CE; Karoryfer Sneakybass (a quiet pizzicato
double bass). Each goes into a fresh folder, then the maps are generated:

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/sgossner/VCSL.git vcsl
(cd vcsl && git sparse-checkout set "Idiophones/Struck Idiophones/Sleigh Bells" \
    "Idiophones/Struck Idiophones/Glockenspiel" "Chordophones/Composite Chordophones/Concert Harp" \
    "Idiophones/Struck Idiophones/Shaker, Small" "Chordophones/Zithers/Grand Piano, Kawai/Sustains") && rm -rf vcsl/.git
git clone --depth 1 --filter=blob:none --sparse https://github.com/sgossner/VSCO-2-CE.git vsco2-ce-xmas
(cd vsco2-ce-xmas && git sparse-checkout set "Woodwinds/Flute/susvib" "Woodwinds/Clarinet/susLong" \
    "Woodwinds/Oboe/Vib" "Keys/Organ/Quiet") && rm -rf vsco2-ce-xmas/.git
mkdir karoryfer.sneakybass && curl -L -o sb.zip \
    https://github.com/sfzinstruments/karoryfer.sneakybass/releases/download/v1.000/Sneakybass_v1.000.zip \
    && unzip -q sb.zip -d karoryfer.sneakybass && rm sb.zip
git clone --depth 1 --filter=blob:none --sparse https://github.com/sgossner/VCSL.git vcsl-extra
(cd vcsl-extra && git sparse-checkout set "Aerophones/Reed Aerophones/Tenor Saxophone/Vibrato" \
    "Aerophones/Reed Aerophones/Tenor Saxophone/Non-Vibrato" \
    "Aerophones/Edge-blown Aerophones/Pipe Organ/Quiet Pedal") && rm -rf vcsl-extra/.git
python -I ../../scripts/setup/make_christmas_sfz.py .
```

Acoustic guitars from FreePats (about 30 MB; the nylon archive is 7z with a
filter macOS `tar` can't read, so use 7-Zip, e.g. `brew install sevenzip`):

```bash
mkdir freepats-nylon && curl -L -o freepats-nylon/a.7z \
    https://freepats.zenvoid.org/Guitar/SpanishClassicalGuitar/SpanishClassicalGuitar-SFZ-20190618.7z \
    && (cd freepats-nylon && 7zz x a.7z && rm a.7z)
mkdir freepats-steel && curl -L -o freepats-steel/a.tar.xz \
    https://freepats.zenvoid.org/Guitar/FSS-SteelStringGuitar/FSS-SteelStringGuitar-SFZ-20200521.tar.xz \
    && (cd freepats-steel && tar -xJf a.tar.xz && rm a.tar.xz)
```

`vcsl-extra` (about 160 MB, CC0) holds a real tenor sax (VCSL "Brett" tenor:
vibrato takes for melodies, two-layer straight sustains for section parts;
without it the tenor plays the alto samples) and the quiet pipe organ's own
pedal rank for the choir style's pedal bass.

The muted trumpet uses the trumpet folder already downloaded for the horns
(`vsco2-ce/Brass/Trumpet/straightM-sus`). Celesta and the choir "aahs" have
no free recorded library here yet, so they play the General
MIDI soundfont's patches (MuseScore_General, MIT).

Grand piano, brush kit, double bass and clean lead guitar (about 3 GB):

```bash
git clone --depth 1 https://github.com/sfzinstruments/SalamanderGrandPiano.git salamander-grand && rm -rf salamander-grand/.git
mkdir karoryfer.swirly-drums && curl -L -o karoryfer.swirly-drums/a.zip \
    https://github.com/sfzinstruments/karoryfer.swirly-drums/releases/download/v1.104/Swirly.Drums_1104.zip \
    && (cd karoryfer.swirly-drums && unzip -q a.zip && rm a.zip)
mkdir karoryfer.meatbass && curl -L -o karoryfer.meatbass/a.zip \
    https://github.com/sfzinstruments/karoryfer.meatbass/releases/download/v1.001/Karoryfer.Meatbass.v1.001.zip \
    && (cd karoryfer.meatbass && unzip -q a.zip && rm a.zip)
mkdir freepats-fsbs-clean && curl -L -o freepats-fsbs-clean/a.7z \
    https://github.com/freepats/electric-guitar-FSBS-clean/releases/download/2026-08-07/EGuitarFSBS-clean-SFZ+FLAC-20260807.7z \
    && (cd freepats-fsbs-clean && 7zz x a.7z && rm a.7z)
```

Electric pianos (about 70 MB):

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/sfzinstruments/GregSullivan.E-Pianos.git gregsullivan.e-pianos
(cd gregsullivan.e-pianos && git sparse-checkout set "Wurlitzer EP200") && rm -rf gregsullivan.e-pianos/.git
git clone --depth 1 --filter=blob:none --sparse https://github.com/sgossner/VCSL.git vcsl-fm
(cd vcsl-fm && git sparse-checkout set "Electrophones/TX81Z/FM Piano") && rm -rf vcsl-fm/.git
python -I ../../scripts/setup/make_christmas_sfz.py .     # writes vcsl-fm/fm_piano.sfz
```

About 4.9 GB on disk in all. A render loads only the samples its notes use.

## Libraries and licences

Only libraries whose licence allows selling and monetising the music made
with them belong here: no NonCommercial (NC) or NoDerivatives (ND) terms.
`tests/unit/test_instrument_licenses.py` fails on an NC/ND licence in this
table, and on any library folder `sampled.py` plays that isn't listed.

| Part | Library | Folder | Licence |
|---|---|---|---|
| Electric piano 1 (GM 4) | Greg Sullivan's Wurlitzer EP200 (sfzinstruments mapping) | gregsullivan.e-pianos | CC BY 3.0: credit "Wurlitzer EP200 samples by Greg Sullivan" |
| Electric piano 2 (GM 5; GM 4 without the Wurlitzer) | VCSL, Yamaha TX81Z "FM Piano" | vcsl-fm | CC0 |
| Electric bass (GM 32-37) | Karoryfer Black And Blue Basses | karoryfer.black-and-blue-basses | CC0 |
| Drum kit | Virtuosity Drums (Versilian Studios / Karoryfer) | virtuosity_drums | CC0 |
| Saxes (GM 64-67) | Karoryfer Weresax | karoryfer.weresax | CC0 |
| Trumpet (56, 59), trombone (57), brass section (61), muted trumpets (59) | VSCO 2 CE | vsco2-ce | CC0 |
| Strings (48-51), spiccato (45), French horn (60), cello (42) | VSCO 2 CE | vsco2-ce-strings | CC0 |
| Guitar lead voice | Karoryfer Black And Green Guitars (Gretsch / Hofner) | karoryfer.black-and-green-guitars | CC0 |
| Grand piano (GM 0-1) | Salamander Grand Piano V3 (Yamaha C5, Alexander Holm; sfzinstruments mapping) | salamander-grand | CC BY 3.0: credit "Salamander Grand Piano by Alexander Holm, CC-BY 3.0" |
| Grand piano fallback (GM 0-1), harp (46), glockenspiel (9), sleigh bells (112), shaker (113) | VCSL (Versilian Studios) | vcsl | CC0 |
| Double bass, bowed (GM 43) | Karoryfer Meatbass (1958 double bass) | karoryfer.meatbass | CC0 |
| Brush kit (GM drum program 40) | Karoryfer Swirly Drums | karoryfer.swirly-drums | CC0 |
| Clean lead guitar (voice "guitar_clean") | FreePats FSBS Electric Guitar Clean #1 (Fender) | freepats-fsbs-clean | CC0 |
| Flute (73), clarinet (71), oboe (68), church organ (19) | VSCO 2 CE | vsco2-ce-xmas | CC0 |
| Upright bass (32) | Karoryfer Sneakybass (1958 Otto Rubner double bass, pizzicato) | karoryfer.sneakybass | CC0 |
| Nylon guitar (24) | FreePats Spanish Classical Guitar | freepats-nylon | CC0 |
| Steel-string guitar (25) | FreePats FSS Steel-String (FlameStudios samples) | freepats-steel | GPL 3 with FreePats' exception: a composition using the sounds is not covered by the GPL |
| Tenor sax (66), organ pedal bass (19, tracks named "pedal") | VCSL (Versilian Studios) | vcsl-extra | CC0 |

Music made with any of them can be used commercially; the Wurlitzer and the
Salamander piano need the credits above (in a track's or video's credits).
`CREDITS.md` at the repo root lists every credit line in one place.

The jlearman jRhodes3c Rhodes used to play GM 4/5. Its sample licence is
CC BY-NC-SA 4.0 (non-commercial), so it was removed; delete the
`jlearman.jRhodes3c` folder if it's still here. Its author offers a
commercial licence on request (jjlearman@gmail.com).
