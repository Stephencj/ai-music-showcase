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

About 2.7 GB on disk. A render loads only the samples its notes use.

## Libraries and licences

| Part | Library | Licence |
|---|---|---|
| Rhodes (EP 1/2) | jlearman jRhodes3c, 1977 Rhodes Mark I | Free to use in your music; redistributing the samples is CC BY-NC-SA 4.0 |
| Electric bass (GM 32-37) | Karoryfer Black And Blue Basses | CC0 |
| Drum kit | Virtuosity Drums (Versilian Studios / Karoryfer) | CC0 |
| Saxes (GM 64-67) | Karoryfer Weresax | CC0 |

Music made with any of them can be used commercially. Don't commit or ship
the jRhodes samples themselves.
