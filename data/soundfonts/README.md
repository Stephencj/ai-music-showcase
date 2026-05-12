# Soundfonts

The render pipeline (`src/audio_processing/render/`) drives FluidSynth
against a `.sf2`/`.sf3` soundfont placed here.

## Auto-resolution

`resolve_soundfont()` (in `soundfont_resolver.py`) picks one in this order:

1. Explicit path passed by the caller.
2. `$AI_MUSIC_SOUNDFONT` environment variable.
3. The largest `.sf3`/`.sf2` in this directory.
4. The 5.7 MB `TimGM6mb.sf2` bundled with `pretty_midi` (low quality
   fallback — the pipeline prints a warning when it falls back here).

## Recommended: MuseScore General SF3 (~38 MB)

Best quality-per-byte for general-purpose work. Free, MIT-style license.

```bash
python -c "from src.audio_processing.render.soundfont_resolver import download_default; download_default()"
```

…or download manually from <https://musescore.org/en/handbook/3/soundfonts-and-sfz-files-installation-and-loading#General>
and drop the `.sf3` here.

## Larger / specialized soundfonts

Place any extra `.sf2`/`.sf3` here. The largest file wins by default —
override with the `--soundfont` CLI flag or the `Soundfont path` UI input
to pin a specific file.

Soundfonts are **not** committed (see `.gitignore`).
