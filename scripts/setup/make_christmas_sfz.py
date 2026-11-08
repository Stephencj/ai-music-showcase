"""Write SFZ maps for the Christmas instruments (all CC0).

The Christmas styles (src/composition/christmas.py) play a grand piano,
harp, glockenspiel, sleigh bells, a shaker, flute / clarinet / oboe, a quiet
pipe organ, pizzicato strings and a muted trumpet from two CC0 libraries:

- VCSL, the Versilian Community Sample Library (github.com/sgossner/VCSL)
- VSCO 2 Community Edition (github.com/sgossner/VSCO-2-CE)

Neither ships SFZ maps for these folders, and the file names follow several
conventions (``GPiano_sus_A#2_v1_rr1_Player.wav``, ``KSHarp_A2_mf1.wav``,
``glock_soft_C5_01.wav``, ``NT5_Man3Quiet_122_rr1.wav``), so each folder's
pitch is measured (YIN) rather than trusted: named folders get one octave
correction for the whole folder, unnamed ones (the organ) a pitch per file.

Download (sparse, about 1 GB in all), each into a fresh folder:

    cd data/instruments
    git clone --depth 1 --filter=blob:none --sparse https://github.com/sgossner/VCSL.git vcsl
    (cd vcsl && git sparse-checkout set "Idiophones/Struck Idiophones/Sleigh Bells" \
        "Idiophones/Struck Idiophones/Glockenspiel" "Chordophones/Composite Chordophones/Concert Harp" \
        "Idiophones/Struck Idiophones/Shaker, Small" "Chordophones/Zithers/Grand Piano, Kawai/Sustains") \
        && rm -rf vcsl/.git
    git clone --depth 1 --filter=blob:none --sparse https://github.com/sgossner/VSCO-2-CE.git vsco2-ce-xmas
    (cd vsco2-ce-xmas && git sparse-checkout set "Woodwinds/Flute/susvib" "Woodwinds/Clarinet/susLong" \
        "Woodwinds/Oboe/Vib" "Keys/Organ/Quiet" "Strings/Violin Section/Pizz" "Strings/Cello Section/pizzT") \
        && rm -rf vsco2-ce-xmas/.git

    python -I scripts/setup/make_christmas_sfz.py data/instruments

The muted trumpet reads the VSCO trumpet folder the horns already use
(``vsco2-ce/Brass/Trumpet/straightM-sus``).
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

NOTES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
# Note name, then a dynamic layer (v1 / mf1 / p1 …) and an optional round robin.
NAMED = re.compile(r"_([A-G]#?)(-?\d+)_(?:(v|pp|p|mp|mf|ff|f)(\d+))?(?:_?(?:rr|RR)?(\d+))?(?:_[A-Za-z]+)?\.wav$")
# glock_soft_C5_01.wav: the dynamic is a word before the note.
WORD_DYN = re.compile(r"_(soft|medium|loud)_([A-G]#?)(-?\d+)_(\d+)\.wav$")
DYN_ORDER = {"pp": 0, "p": 1, "soft": 1, "mp": 2, "medium": 2, "mf": 3, "f": 4, "loud": 4, "ff": 5}

# (output file under root, folder under root, attack s, release s, loop mode, global extras)
PITCHED = [
    ("vcsl/piano_kawai.sfz", "vcsl/Chordophones/Zithers/Grand Piano, Kawai/Sustains", 0.002, 0.45, "no_loop",
     "amp_veltrack=85"),
    ("vcsl/harp.sfz", "vcsl/Chordophones/Composite Chordophones/Concert Harp", 0.001, 1.2, "one_shot",
     "amp_veltrack=70"),
    ("vcsl/glockenspiel.sfz", "vcsl/Idiophones/Struck Idiophones/Glockenspiel", 0.001, 1.5, "one_shot",
     "amp_veltrack=60"),
    ("vsco2-ce-xmas/flute_sus.sfz", "vsco2-ce-xmas/Woodwinds/Flute/susvib", 0.06, 0.3, "no_loop", "amp_veltrack=50"),
    ("vsco2-ce-xmas/clarinet_sus.sfz", "vsco2-ce-xmas/Woodwinds/Clarinet/susLong", 0.05, 0.3, "no_loop",
     "amp_veltrack=50"),
    ("vsco2-ce-xmas/oboe_sus.sfz", "vsco2-ce-xmas/Woodwinds/Oboe/Vib", 0.05, 0.3, "no_loop", "amp_veltrack=50"),
    ("vsco2-ce-xmas/violins_pizz.sfz", "vsco2-ce-xmas/Strings/Violin Section/Pizz", 0.001, 0.4, "one_shot",
     "amp_veltrack=70"),
    ("vsco2-ce-xmas/cellos_pizz.sfz", "vsco2-ce-xmas/Strings/Cello Section/pizzT", 0.001, 0.5, "one_shot",
     "amp_veltrack=70"),
    ("vsco2-ce/trumpet_muted_sus.sfz", "vsco2-ce/Brass/Trumpet/straightM-sus", 0.05, 0.3, "no_loop",
     "amp_veltrack=50"),
]
# Unnamed samples, pitch measured per file: (output, folder, file glob, attack, release, loop, extras).
# The organ's manual rank only: its pedal rank doubles the low octaves in another colour.
MEASURED = [
    ("vsco2-ce-xmas/organ_quiet.sfz", "vsco2-ce-xmas/Keys/Organ/Quiet", "*Man3Quiet*.wav", 0.08, 0.5, "no_loop",
     "amp_veltrack=20"),
]


def _parse(name: str):
    """(named MIDI note, dynamic rank, round robin) or None."""
    m = WORD_DYN.search(name)
    if m:
        return NOTES[m.group(2)] + 12 * (int(m.group(3)) + 1), DYN_ORDER[m.group(1)], int(m.group(4))
    m = NAMED.search(name)
    if not m:
        return None
    note = NOTES[m.group(1)] + 12 * (int(m.group(2)) + 1)
    dyn = DYN_ORDER.get(m.group(3) or "", 3) * 10 + int(m.group(4) or 1) if m.group(3) != "v" \
        else int(m.group(4))
    return note, dyn, int(m.group(5) or 1)


def _measure(path: Path) -> float | None:
    """The sample's pitch as a (fractional) MIDI note, or None."""
    import librosa
    import soundfile as sf
    x, sr = sf.read(str(path), always_2d=True)
    x = x.mean(axis=1)
    if not len(x) or float(np.abs(x).max()) <= 0:
        return None
    a = int(np.argmax(np.abs(x) > 0.1 * np.abs(x).max()))
    seg = x[a + int(0.08 * sr): a + int(0.7 * sr)]
    if len(seg) < 4096:
        return None
    hz = librosa.yin(seg, fmin=30, fmax=4200, sr=sr, frame_length=4096)
    hz = hz[np.isfinite(hz)]
    if not len(hz):
        return None
    return 69 + 12 * float(np.log2(np.median(hz) / 440.0))


def _octave_shift(files: list[Path]) -> int:
    diffs = []
    for f in files[:: max(1, len(files) // 8)][:8]:
        measured = _measure(f)
        if measured is not None:
            diffs.append(measured - _parse(f.name)[0])
    return int(12 * round(float(np.median(diffs)) / 12)) if diffs else 0


def _regions(notes: dict[int, dict[int, list[Path]]], root: Path, attack: float, release: float,
             loop: str, tunes: dict[Path, float] | None = None) -> list[str]:
    keys = sorted(notes)
    out = []
    for i, key in enumerate(keys):
        lo = 0 if i == 0 else (keys[i - 1] + key) // 2 + 1
        hi = 127 if i == len(keys) - 1 else (key + keys[i + 1]) // 2
        layers = sorted(notes[key])
        for li, layer in enumerate(layers):
            lovel, hivel = 1 + (127 * li) // len(layers), (127 * (li + 1)) // len(layers)
            rrs = notes[key][layer]
            for ri, f in enumerate(rrs):
                tune = f" tune={int(round(tunes[f]))}" if tunes and f in tunes else ""
                out.append(f"<region> sample={f.relative_to(root).as_posix()} lokey={lo} hikey={hi} "
                           f"pitch_keycenter={key}{tune} lovel={lovel} hivel={hivel} seq_length={len(rrs)} "
                           f"seq_position={ri + 1} ampeg_attack={attack} ampeg_release={release} loop_mode={loop}")
    return out


def _write(path: Path, header: str, extras: str, regions: list[str]) -> None:
    path.write_text(f"// Generated by scripts/setup/make_christmas_sfz.py. {header}\n"
                    f"<global> {extras}\n" + "\n".join(regions) + "\n")
    print(f"wrote {path}: {len(regions)} regions")


def pitched(root: Path) -> None:
    for out, folder, attack, release, loop, extras in PITCHED:
        path = root / folder
        files = sorted(p for p in path.glob("*.wav") if _parse(p.name)) if path.exists() else []
        if not files:
            print(f"skipped {out}: {folder} not downloaded")
            continue
        shift = _octave_shift(files)
        notes: dict[int, dict[int, list[Path]]] = defaultdict(lambda: defaultdict(list))
        for f in files:
            note, dyn, _rr = _parse(f.name)
            notes[note + shift][dyn].append(f)
        _write(root / out, f"{folder} (CC0), names shifted {shift:+d}.", extras,
               _regions(notes, (root / out).parent, attack, release, loop))


def measured(root: Path) -> None:
    for out, folder, pattern, attack, release, loop, extras in MEASURED:
        path = root / folder
        files = sorted(path.glob(pattern)) if path.exists() else []
        if not files:
            print(f"skipped {out}: {folder} not downloaded")
            continue
        notes: dict[int, dict[int, list[Path]]] = defaultdict(lambda: defaultdict(list))
        tunes: dict[Path, float] = {}
        for f in files:
            m = _measure(f)
            if m is None:
                continue
            key = int(round(m))
            tunes[f] = (key - m) * 100.0          # cents that bring it to the key
            notes[key][1].append(f)
        _write(root / out, f"{folder} (CC0), pitch measured per file.", extras,
               _regions(notes, (root / out).parent, attack, release, loop, tunes))


def percussion(root: Path) -> None:
    """Sleigh bells and shaker as one-shot kits on fixed keys (the
    christmas techniques write these keys):

    sleigh bells: 60 hit (round robins), 61 loud hit, 62 shake, 63 long shake.
    shaker: 60 forward stroke, 61 back stroke, 62 accent (slap), 63 roll.
    """
    kits = {
        "vcsl/sleigh_bells.sfz": ("vcsl/Idiophones/Struck Idiophones/Sleigh Bells", {
            60: ["Sleighbells_Hit_rr1_Mid.wav", "Sleighbells_Hit_rr2_Mid.wav", "sleighbell2_hit_2.wav"],
            61: ["sleighbell2_hit_loud.wav"],
            62: ["sleighbell2_shake1.wav"],
            63: ["sleighbell1_shake1.wav"],
        }),
        "vcsl/shaker.sfz": ("vcsl/Idiophones/Struck Idiophones/Shaker, Small", {
            60: ["Mid_ShakerDouble_Down_rr1.wav", "Mid_ShakerDouble_Down_rr2.wav"],
            61: ["Mid_ShakerDouble_Up_rr1.wav", "Mid_ShakerDouble_Up_rr2.wav"],
            62: ["Mid_Shaker_Slap_rr1.wav", "Mid_Shaker_Slap_rr2.wav"],
            63: ["Mid_Shaker_Roll_Fast_rr1.wav", "Mid_Shaker_Roll_Fast_rr2.wav"],
        }),
    }
    for out, (folder, keys) in kits.items():
        path = root / folder
        if not path.exists():
            print(f"skipped {out}: {folder} not downloaded")
            continue
        regions = []
        for key, names in keys.items():
            names = [n for n in names if (path / n).exists()]
            for ri, n in enumerate(names):
                rel = (path / n).relative_to((root / out).parent).as_posix()
                regions.append(f"<region> sample={rel} key={key} pitch_keytrack=0 seq_length={len(names)} "
                               f"seq_position={ri + 1} ampeg_release=0.6 loop_mode=one_shot")
        _write(root / out, f"{folder} (CC0), fixed keys 60-63.", "amp_veltrack=80", regions)


def main(root: str) -> None:
    base = Path(root).resolve()
    pitched(base)
    measured(base)
    percussion(base)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/instruments")
