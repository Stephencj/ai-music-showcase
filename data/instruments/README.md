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
for r in jlearman.jRhodes3c karoryfer.black-and-blue-basses virtuosity_drums karoryfer.weresax; do
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

About 3.5 GB on disk in all. A render loads only the samples its notes use.

## Libraries and licences

| Part | Library | Licence |
|---|---|---|
| Rhodes (EP 1/2) | jlearman jRhodes3c, 1977 Rhodes Mark I | Free to use in your music; redistributing the samples is CC BY-NC-SA 4.0 |
| Electric bass (GM 32-37) | Karoryfer Black And Blue Basses | CC0 |
| Drum kit | Virtuosity Drums (Versilian Studios / Karoryfer) | CC0 |
| Saxes (GM 64-67) | Karoryfer Weresax | CC0 |
| Trumpet (56, 59), trombone (57), brass section (61) | VSCO 2 CE staccato | CC0 |
| Guitar lead voice | Karoryfer Black And Green Guitars (Gretsch / Hofner) | CC0 |

Music made with any of them can be used commercially. Don't commit or ship
the jRhodes samples themselves.
