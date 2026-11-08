"""A small offline SFZ sample player.

Plays a track's notes through a sampled instrument described by an ``.sfz``
file (a text map of recorded samples: which sample plays for which key and
velocity, with round robins, envelopes, mic faders and so on). Free SFZ
libraries of real instruments (Rhodes, bass guitar, jazz drum kits, sax)
sound far more like a recording than the General MIDI soundfont, and the
notes stay fully under the composer's control.

Supported, as these libraries use it:

- ``#define`` / ``#include``, ``<control>`` (``default_path``, ``set_ccN``,
  ``note_offset``), ``<global>`` / ``<master>`` / ``<group>`` / ``<region>``
  inheritance, ``<curve>``.
- Region choice: ``lokey/hikey/key``, ``lovel/hivel``, ``locc/hicc`` against
  the default CC values, ``seq_length/seq_position`` round robins,
  ``lorand/hirand``, keyswitches at their ``sw_default``, ``trigger`` =
  attack / first / legato / release.
- Sound: ``pitch_keycenter``, ``pitch_keytrack``, ``transpose``, ``tune``
  (+ ``tune_ccN`` / ``pitch_onccN`` with curves), ``volume`` (+ ``_onccN``),
  ``amplitude`` (+ ``_onccN`` as a fader), ``amp_veltrack`` /
  ``amp_velcurve_N``, ``amp_keytrack``, ``pan`` / ``width`` (+ ``_onccN``),
  velocity and CC crossfades, ``offset``, ``delay``, ``ampeg_*`` (DAHDSR),
  ``loop_mode`` (loop points from the opcodes or the file's ``smpl``
  chunk, also inside FLAC), ``group`` / ``off_by`` chokes with
  ``off_mode`` / ``off_time``, ``note_polyphony``, ``rt_decay``.

Ignored (logged once): filters, EQ, LFOs and effects. The mixer adds EQ,
compression and reverb afterwards.
"""

from __future__ import annotations

import logging
import math
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

_NOTE_NAMES = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
_NOTE_RE = re.compile(r"^([a-gA-G])([#b]?)(-?\d+)$")


def note_number(value: str | int | float | None, default: Optional[int] = None) -> Optional[int]:
    """SFZ key value → MIDI note (c4 = 60). Accepts numbers or names."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if not s:
        return default
    try:
        return int(float(s))
    except ValueError:
        pass
    m = _NOTE_RE.match(s)
    if not m:
        return default
    n = _NOTE_NAMES[m.group(1).lower()] + {"#": 1, "b": -1, "": 0}[m.group(2)]
    return (int(m.group(3)) + 1) * 12 + n


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_HEADER_OR_OPCODE = re.compile(r"<(\w+)>|([A-Za-z0-9_$]+)=")
_DEFINE = re.compile(r"^\s*#define\s+(\$\w+)\s+(.*?)\s*$", re.M)
_INCLUDE = re.compile(r'\s*#include\s+"([^"]+)"')
_FREE_TEXT_OPCODES = ("sample", "default_path") + tuple(f"label{s}" for s in ("", "_cc", "_key"))


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _preprocess(path: Path, root_dir: Path, defines: dict[str, str], depth: int = 0) -> str:
    """Expand #include (relative to the root file's folder) and #define."""
    if depth > 16:
        raise ValueError(f"sfz: #include nested too deep at {path}")
    text = _strip_comments(path.read_text(errors="replace"))
    out: list[str] = []
    pos = 0
    # A #define takes its whole line; an #include can also sit mid-line
    # (Salamander: ``<group> #include "vel_01.txt" lovel=1 #include "region.txt"``).
    for m in re.finditer(r'^\s*#define\b[^\n]*|#include\s+"[^"]*"', text, re.M):
        out.append(_substitute(text[pos:m.start()], defines))
        line = m.group(0)
        d = _DEFINE.match(line)
        if d:
            defines[d.group(1)] = _substitute(d.group(2), defines)
        else:
            i = _INCLUDE.match(line)
            if i:
                inc = (root_dir / _substitute(i.group(1), defines)).resolve()
                if inc.exists():
                    out.append(_preprocess(inc, root_dir, defines, depth + 1))
                else:
                    logger.warning("sfz: missing #include %s", inc)
        pos = m.end()
    out.append(_substitute(text[pos:], defines))
    return "\n".join(out)


def _group_id(value: Optional[str]) -> int:
    """A group / off_by number. Tolerates a library's typo'd define left
    with trailing text (Swirly Drums writes ``$HTQTRGRPP``, which expands to
    ``15P``): the leading number counts; no number is group 0."""
    m = re.match(r"\s*(-?\d+)", str(value or ""))
    return int(m.group(1)) if m else 0


def _substitute(text: str, defines: dict[str, str]) -> str:
    if not defines or "$" not in text:
        return text
    # Longest names first so $FOO_BAR wins over $FOO.
    for name in sorted(defines, key=len, reverse=True):
        text = text.replace(name, defines[name])
    return text


def _tokens(text: str) -> Iterable[tuple[str, str, str]]:
    """Yield ("header", name, "") and ("opcode", name, value)."""
    matches = list(_HEADER_OR_OPCODE.finditer(text))
    for i, m in enumerate(matches):
        if m.group(1):
            yield "header", m.group(1).lower(), ""
            continue
        name = m.group(2)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        raw = text[m.end():end]
        if name in _FREE_TEXT_OPCODES or name.startswith("label"):
            value = raw.strip().replace("\\", "/")
        else:
            parts = raw.split()
            value = parts[0] if parts else ""
        yield "opcode", name, value


@dataclass
class Region:
    op: dict[str, str]
    sample_path: Optional[Path]
    lokey: int
    hikey: int
    lovel: int
    hivel: int
    keycenter: int
    trigger: str
    seq_length: int
    seq_position: int
    group: int
    off_by: int
    seq_counter: int = 0

    def f(self, name: str, default: float = 0.0) -> float:
        v = self.op.get(name)
        if v is None or v == "":
            return default
        try:
            return float(v)
        except ValueError:
            return default

    def i(self, name: str, default: int = 0) -> int:
        return int(self.f(name, default))


@dataclass
class SfzInstrument:
    path: Path
    regions: list[Region]
    cc_defaults: dict[int, float] = field(default_factory=dict)
    curves: dict[int, np.ndarray] = field(default_factory=dict)
    note_offset: int = 0
    keyswitch: Optional[int] = None


def load_sfz(path: str | Path, cc_overrides: Optional[dict[int, float]] = None) -> SfzInstrument:
    """Parse an .sfz file into regions with their inherited opcodes."""
    path = Path(path).resolve()
    text = _preprocess(path, path.parent, {})

    control: dict[str, str] = {}
    global_op: dict[str, str] = {}
    master_op: dict[str, str] = {}
    group_op: dict[str, str] = {}
    region_op: Optional[dict[str, str]] = None
    curve_op: Optional[dict[str, str]] = None
    header = ""
    raw_regions: list[dict[str, str]] = []
    raw_curves: list[dict[str, str]] = []

    def close_region() -> None:
        nonlocal region_op
        if region_op is not None:
            raw_regions.append({**global_op, **master_op, **group_op, **region_op,
                                "__default_path": control.get("default_path", "")})
            region_op = None

    for kind, name, value in _tokens(text):
        if kind == "header":
            close_region()
            if curve_op is not None:
                raw_curves.append(curve_op)
                curve_op = None
            header = name
            if name == "global":
                global_op, master_op, group_op = {}, {}, {}
            elif name == "master":
                master_op, group_op = {}, {}
            elif name == "group":
                group_op = {}
            elif name == "region":
                region_op = {}
            elif name == "curve":
                curve_op = {}
            continue
        if header == "control":
            control[name] = value
        elif header == "global":
            global_op[name] = value
        elif header == "master":
            master_op[name] = value
        elif header == "group":
            group_op[name] = value
        elif header == "region" and region_op is not None:
            region_op[name] = value
        elif header == "curve" and curve_op is not None:
            curve_op[name] = value
    close_region()
    if curve_op is not None:
        raw_curves.append(curve_op)

    cc_defaults: dict[int, float] = {}
    for k, v in control.items():
        if k.startswith("set_cc"):
            try:
                cc_defaults[int(k[6:])] = float(v)
            except ValueError:
                pass
        elif k.startswith("set_hdcc"):
            try:
                cc_defaults[int(k[8:])] = float(v) * 127.0
            except ValueError:
                pass
    if cc_overrides:
        cc_defaults.update(cc_overrides)
    note_offset = int(float(control.get("note_offset", "0") or 0))

    regions: list[Region] = []
    for op in raw_regions:
        sample = op.get("sample", "")
        if not sample:
            continue
        if sample.startswith("*"):
            sample_path = None if sample == "*silence" else None
            if sample != "*silence":
                continue  # generators (*sine, *noise …) aren't used by these libraries
        else:
            # Windows-made maps write "electric\\a4.wav".
            sample_path = (path.parent / op.get("__default_path", "").replace("\\", "/")
                           / sample.replace("\\", "/")).resolve()
        key = note_number(op.get("key"))
        lokey = note_number(op.get("lokey"), key if key is not None else 0)
        hikey = note_number(op.get("hikey"), key if key is not None else 127)
        keycenter_raw = op.get("pitch_keycenter")
        keycenter = note_number(keycenter_raw, key if key is not None else 60)
        regions.append(Region(
            op=op,
            sample_path=sample_path,
            lokey=lokey, hikey=hikey,
            lovel=int(float(op.get("lovel") or 0)),
            hivel=int(float(op.get("hivel", 127) or 127)),
            keycenter=keycenter if keycenter is not None else 60,
            trigger=op.get("trigger", "attack"),
            seq_length=max(1, int(float(op.get("seq_length", 1) or 1))),
            seq_position=max(1, int(float(op.get("seq_position", 1) or 1))),
            group=_group_id(op.get("group")),
            off_by=_group_id(op.get("off_by")),
        ))

    curves: dict[int, np.ndarray] = {}
    for c in raw_curves:
        idx = int(float(c.get("curve_index", -1) or -1))
        if idx < 0:
            continue
        pts = sorted((int(k[1:]), float(v)) for k, v in c.items() if re.fullmatch(r"v\d+", k))
        if pts:
            xs, ys = zip(*pts)
            curves[idx] = np.interp(np.arange(128), xs, ys).astype(np.float64)

    # Keyswitch: the first sw_default wins; regions with sw_last only play when it matches.
    keyswitch = None
    for r in regions:
        if "sw_default" in r.op:
            keyswitch = note_number(r.op["sw_default"])
            break
    if keyswitch is None:
        sws = [note_number(r.op["sw_last"]) for r in regions if "sw_last" in r.op]
        sws = [s for s in sws if s is not None]
        keyswitch = min(sws) if sws else None

    unsupported = sorted({k for r in regions for k in r.op
                          if k.startswith(("fil", "cutoff", "resonance", "eq", "lfo", "fileg", "pitcheg"))})
    if unsupported:
        logger.info("sfz %s: ignoring %s", path.name, ", ".join(unsupported[:12]))

    return SfzInstrument(path=path, regions=regions, cc_defaults=cc_defaults,
                         curves=curves, note_offset=note_offset, keyswitch=keyswitch)


# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------

@dataclass
class Sample:
    data: np.ndarray          # (2, N) float32
    sample_rate: int
    loop: Optional[tuple[int, int]]


def _smpl_loop(chunk: bytes) -> Optional[tuple[int, int]]:
    """Loop points from a RIFF 'smpl' chunk body."""
    if len(chunk) < 36:
        return None
    n_loops = struct.unpack_from("<I", chunk, 28)[0]
    if n_loops < 1 or len(chunk) < 36 + 24:
        return None
    start, end = struct.unpack_from("<II", chunk, 36 + 8)
    return (int(start), int(end)) if end > start else None


def _riff_chunks(data: bytes, offset: int = 12) -> Iterable[tuple[bytes, bytes]]:
    pos = offset
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        yield cid, data[pos + 8:pos + 8 + size]
        pos += 8 + size + (size & 1)


def _file_loop(path: Path) -> Optional[tuple[int, int]]:
    """Loop points from a WAV smpl chunk, or a FLAC's embedded RIFF blocks."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4)
            if head == b"RIFF":
                fh.seek(0)
                data = fh.read()
                for cid, body in _riff_chunks(data):
                    if cid == b"smpl":
                        return _smpl_loop(body)
                return None
            if head != b"fLaC":
                return None
            riff = b""
            while True:
                hdr = fh.read(4)
                if len(hdr) < 4:
                    break
                last = hdr[0] & 0x80
                btype = hdr[0] & 0x7F
                size = int.from_bytes(hdr[1:4], "big")
                body = fh.read(size)
                if btype == 2 and body[:4] == b"riff":
                    riff += body[4:]
                if last:
                    break
            # flac --keep-foreign-metadata stores the WAV's chunks in order.
            pos = 0
            while pos + 8 <= len(riff):
                cid = riff[pos:pos + 4]
                if cid == b"RIFF":
                    pos += 12
                    continue
                size = struct.unpack_from("<I", riff, pos + 4)[0]
                if cid == b"smpl":
                    return _smpl_loop(riff[pos + 8:pos + 8 + size])
                pos += 8 + (size if cid != b"data" else 0) + (size & 1 if cid != b"data" else 0)
    except OSError:
        return None
    return None


class SampleCache:
    def __init__(self) -> None:
        self._cache: dict[Path, Optional[Sample]] = {}

    def get(self, path: Path) -> Optional[Sample]:
        if path in self._cache:
            return self._cache[path]
        sample: Optional[Sample] = None
        try:
            data, sr = sf.read(str(path), dtype="float32", always_2d=True)
            data = data.T
            if data.shape[0] == 1:
                data = np.vstack([data, data])
            elif data.shape[0] > 2:
                data = data[:2]
            sample = Sample(np.ascontiguousarray(data), int(sr), _file_loop(path))
        except Exception:
            logger.warning("sfz: can't read sample %s", path)
        self._cache[path] = sample
        return sample


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

@dataclass
class Note:
    pitch: int
    start: float
    end: float
    velocity: int


@dataclass
class _Voice:
    region: Region
    sample: Optional[Sample]
    start: int                # output sample index
    note_off: Optional[int]   # output sample where the key is released (None = one-shot)
    key: int
    velocity: int
    gain: float
    pan: float
    width: float
    ratio: float              # source samples per output sample
    offset: int
    cut_at: Optional[int] = None   # choke / polyphony stop
    cut_time: float = 0.006
    vibrato: Optional["Vibrato"] = None


@dataclass(frozen=True)
class Vibrato:
    """Delayed pitch vibrato for held notes (how a player eases a long note)."""
    cents: float = 15.0          # depth, ± cents
    rate: float = 5.3            # Hz
    delay: float = 0.12          # seconds before it starts
    ramp: float = 0.15           # seconds to reach full depth
    min_length: float = 0.28     # only notes at least this long


def _builtin_curve(index: int, x: float) -> float:
    """SFZ built-in curves; x in 0..1."""
    if index == 1:
        return x * 2.0 - 1.0
    if index == 2:
        return 1.0 - x
    if index == 3:
        return 1.0 - x * 2.0
    if index == 4:
        return x * x
    if index == 5:
        return math.sqrt(x)
    if index == 6:
        return math.sqrt(1.0 - x)
    return x


class SfzRenderer:
    """Render notes through one SFZ instrument to a stereo buffer."""

    def __init__(self, instrument: SfzInstrument, sample_rate: int = 44100, *,
                 cache: Optional[SampleCache] = None, seed: int = 1, sample_tune=None,
                 vibrato: Optional[Vibrato] = None) -> None:
        self.inst = instrument
        self.sr = sample_rate
        self.cache = cache or SampleCache()
        self.rng = np.random.default_rng(seed)
        # Optional (path, sample, keycenter) -> cents sharp, corrected per note.
        self.sample_tune = sample_tune
        self.vibrato = vibrato

    # -- modulation helpers -------------------------------------------------

    def _cc(self, n: int) -> float:
        return float(self.inst.cc_defaults.get(n, 0.0))

    def _curve(self, index: int, cc_value: float) -> float:
        x = min(max(cc_value / 127.0, 0.0), 1.0)
        if index in self.inst.curves:
            return float(np.interp(x * 127.0, np.arange(128), self.inst.curves[index]))
        return _builtin_curve(index, x)

    def _cc_sum(self, r: Region, prefix: str) -> float:
        """Σ depth × curve(cc) over opcodes like ``volume_onccN``."""
        total = 0.0
        for k, v in r.op.items():
            if not k.startswith(prefix):
                continue
            rest = k[len(prefix):]
            if not rest.isdigit():
                continue
            n = int(rest)
            try:
                depth = float(v)
            except ValueError:
                continue
            stem = prefix[:-5] if prefix.endswith("_oncc") else prefix[:-3] if prefix.endswith("_cc") else prefix[:-2]
            curve = r.i(f"{stem}_curvecc{n}", 0)
            total += depth * self._curve(curve, self._cc(n))
        return total

    def _eg(self, r: Region, stage: str, default: float = 0.0) -> float:
        """An ampeg stage with its CC modulation (``ampeg_hold_oncc71`` …)."""
        name = f"ampeg_{stage}"
        value = r.f(name, default) + self._cc_sum(r, f"{name}_oncc")
        # SFZ v1 spelling: ampeg_attackcc24.
        value += self._cc_sum(r, f"{name}cc") if any(k.startswith(f"{name}cc") for k in r.op) else 0.0
        return max(value, 0.0)

    def _cc_ok(self, r: Region) -> bool:
        for k, v in r.op.items():
            if k.startswith("locc") and k[4:].isdigit():
                n = int(k[4:])
                if self._cc(n) < float(v):
                    return False
            elif k.startswith("hicc") and k[4:].isdigit():
                n = int(k[4:])
                if self._cc(n) > float(v):
                    return False
            elif k.startswith(("on_locc", "on_hicc", "start_locc", "start_hicc")):
                return False  # CC-triggered regions never play from notes
        return True

    def _xfade(self, r: Region, kind: str, value: float) -> float:
        """Velocity / key / CC crossfade gain (power curve by default)."""
        gain = 1.0
        lo_in, hi_in = r.op.get(f"xfin_lo{kind}"), r.op.get(f"xfin_hi{kind}")
        lo_out, hi_out = r.op.get(f"xfout_lo{kind}"), r.op.get(f"xfout_hi{kind}")
        power = r.op.get(f"xf_{'vel' if kind == 'vel' else 'key' if kind == 'key' else 'cc'}curve", "power") != "gain"

        def shape(t: float) -> float:
            t = min(max(t, 0.0), 1.0)
            return math.sqrt(t) if power else t

        if lo_in is not None and hi_in is not None:
            lo, hi = float(note_number(lo_in, 0) if kind == "key" else lo_in), float(note_number(hi_in, 127) if kind == "key" else hi_in)
            if value < lo:
                return 0.0
            if hi > lo and value < hi:
                gain *= shape((value - lo) / (hi - lo))
        if lo_out is not None and hi_out is not None:
            lo, hi = float(note_number(lo_out, 0) if kind == "key" else lo_out), float(note_number(hi_out, 127) if kind == "key" else hi_out)
            if value > hi:
                return 0.0
            if hi > lo and value > lo:
                gain *= shape((hi - value) / (hi - lo))
        return gain

    def _cc_xfade(self, r: Region) -> float:
        gain = 1.0
        for k in r.op:
            m = re.fullmatch(r"xf(in|out)_locc(\d+)", k)
            if not m:
                continue
            n = m.group(2)
            lo = float(r.op[k])
            hi = float(r.op.get(f"xf{m.group(1)}_hicc{n}", lo))
            v = self._cc(int(n))
            if hi <= lo:
                # No fade range (only a lo given, e.g. Shinyguitar's
                # xfout_locc100=0): a step at lo, full gain on its own side.
                t = float(v >= lo) if m.group(1) == "in" else float(v <= lo)
            else:
                t = min(max((v - lo) / (hi - lo), 0.0), 1.0)
                if m.group(1) == "out":
                    t = 1.0 - t
            gain *= math.sqrt(t)
        return gain

    def _velocity_gain(self, r: Region, vel: int) -> float:
        pts = sorted((int(k[13:]), float(v)) for k, v in r.op.items()
                     if k.startswith("amp_velcurve_") and k[13:].isdigit())
        if pts:
            xs, ys = zip(*([(0, 0.0)] + pts if pts[0][0] > 0 else pts))
            curve = float(np.interp(vel, xs, ys))
        else:
            curve = (vel / 127.0) ** 2
        track = r.f("amp_veltrack", 100.0) / 100.0
        if track >= 0:
            return (1.0 - track) + track * curve
        return 1.0 + track * curve  # negative tracking: louder when softer

    # -- selection -----------------------------------------------------------

    def _matches(self, r: Region, key: int, vel: int, trigger: str, held: int) -> bool:
        if not (r.lokey <= key <= r.hikey and r.lovel <= vel <= r.hivel):
            return False
        t = r.trigger
        if trigger == "release":
            if t not in ("release", "release_key"):
                return False
        else:
            if t in ("release", "release_key"):
                return False
            if t == "first" and held > 0:
                return False
            if t == "legato" and held == 0:
                return False
        if "sw_last" in r.op and note_number(r.op["sw_last"]) != self.inst.keyswitch:
            return False
        if "sw_previous" in r.op:
            return False
        return self._cc_ok(r)

    def _pick(self, key: int, vel: int, trigger: str, held: int) -> list[Region]:
        rand = float(self.rng.random())
        chosen: list[Region] = []
        for r in self.inst.regions:
            if not self._matches(r, key, vel, trigger, held):
                continue
            r.seq_counter += 1
            if ((r.seq_counter - 1) % r.seq_length) + 1 != r.seq_position:
                continue
            if not (r.f("lorand", 0.0) <= rand < r.f("hirand", 1.0) or (rand == 1.0 and r.f("hirand", 1.0) >= 1.0)):
                continue
            chosen.append(r)
        return chosen

    # -- voices ---------------------------------------------------------------

    def _voice(self, r: Region, key: int, vel: int, start_s: float, end_s: Optional[float],
               held_seconds: float = 0.0) -> Optional[_Voice]:
        sample = self.cache.get(r.sample_path) if r.sample_path is not None else None
        if r.sample_path is not None and sample is None:
            return None
        src_sr = sample.sample_rate if sample else self.sr

        semis = (key - r.keycenter) * r.f("pitch_keytrack", 100.0) / 100.0
        semis += r.f("transpose", 0.0)
        cents = r.f("tune", 0.0) + r.f("pitch", 0.0) + self._cc_sum(r, "tune_cc") + self._cc_sum(r, "pitch_oncc")
        if self.sample_tune is not None and sample is not None and r.sample_path is not None:
            cents -= self.sample_tune(r.sample_path, sample, r.keycenter)
        cents += r.f("pitch_veltrack", 0.0) * vel / 127.0
        if "pitch_random" in r.op:
            cents += (float(self.rng.random()) * 2 - 1) * r.f("pitch_random")
        ratio = (2.0 ** ((semis + cents / 100.0) / 12.0)) * src_sr / self.sr

        db = r.f("volume", 0.0) + self._cc_sum(r, "volume_oncc") + self._cc_sum(r, "gain_cc")
        db += r.f("amp_keytrack", 0.0) * (key - note_number(r.op.get("amp_keycenter"), 60))
        if "amp_random" in r.op:
            db += float(self.rng.random()) * r.f("amp_random")
        if trigger_is_release(r) and held_seconds > 0:
            db -= r.f("rt_decay", 0.0) * held_seconds
        amp = r.f("amplitude", 100.0) / 100.0
        for k, v in r.op.items():
            if k.startswith("amplitude_oncc") and k[14:].isdigit():
                n = int(k[14:])
                curve = r.i(f"amplitude_curvecc{n}", 0)
                amp *= float(v) / 100.0 * self._curve(curve, self._cc(n))
        gain = (10 ** (db / 20.0)) * amp * self._velocity_gain(r, vel)
        gain *= self._xfade(r, "vel", vel) * self._xfade(r, "key", key) * self._cc_xfade(r)
        if gain <= 1e-5:
            return None

        pan = (r.f("pan", 0.0) + self._cc_sum(r, "pan_oncc")) / 100.0
        width = (r.f("width", 100.0) + self._cc_sum(r, "width_oncc")) / 100.0

        delay = r.f("delay", 0.0) + float(self.rng.random()) * r.f("delay_random", 0.0)
        start = int(round((start_s + delay) * self.sr))
        offset = r.i("offset", 0) + int(self._cc_sum(r, "offset_oncc"))
        offset += int(float(self.rng.random()) * r.f("offset_random", 0.0))

        one_shot = r.op.get("loop_mode") == "one_shot" or trigger_is_release(r)
        note_off = None if one_shot or end_s is None else int(round(end_s * self.sr))
        vib = None
        if self.vibrato is not None and end_s is not None and end_s - start_s >= self.vibrato.min_length:
            vib = self.vibrato
        return _Voice(region=r, sample=sample, start=start, note_off=note_off, key=key,
                      velocity=vel, gain=gain, pan=max(-1.0, min(1.0, pan)),
                      width=max(-1.0, min(1.0, width)), ratio=ratio, offset=offset, vibrato=vib)

    def _envelope(self, v: _Voice, length: int) -> np.ndarray:
        r = v.region
        sr = self.sr
        eg = self._eg
        delay = int(eg(r, "delay") * sr)
        attack = max(int(eg(r, "attack") * sr), 1)
        hold = int(eg(r, "hold") * sr)
        decay = int(eg(r, "decay") * sr)
        sustain = min(max(eg(r, "sustain", 100.0) / 100.0, 0.0), 1.0)
        start_level = r.f("ampeg_start", 0.0) / 100.0

        env = np.full(length, sustain, dtype=np.float32)
        pos = 0
        seg = min(delay, length)
        env[:seg] = 0.0
        pos = seg
        seg = min(attack, length - pos)
        if seg > 0:
            env[pos:pos + seg] = np.linspace(start_level, 1.0, seg, endpoint=False)
            pos += seg
        seg = min(hold, length - pos)
        if seg > 0:
            env[pos:pos + seg] = 1.0
            pos += seg
        seg = min(decay, length - pos)
        if seg > 0 and sustain < 1.0:
            # Exponential-ish decay to sustain like most samplers.
            t = np.linspace(0.0, 1.0, seg, endpoint=False, dtype=np.float32)
            env[pos:pos + seg] = sustain + (1.0 - sustain) * np.exp(-5.0 * t)
            pos += seg

        stop = None
        rel_time = self._eg(r, "release")
        if v.note_off is not None:
            stop = v.note_off - v.start
        if v.cut_at is not None:
            cut = v.cut_at - v.start
            if stop is None or cut < stop:
                stop = cut
                rel_time = v.cut_time
        if stop is not None and stop < length:
            stop = max(stop, 0)
            level = float(env[stop]) if stop < length else 0.0
            rel = max(int(rel_time * sr), 32)
            seg = min(rel, length - stop)
            # sfizz-style exponential release (−60 dB over the release time).
            t = np.arange(seg, dtype=np.float32) / rel
            env[stop:stop + seg] = level * np.power(10.0, -3.0 * t)
            env[stop + seg:] = 0.0
        return env

    def _voice_length(self, v: _Voice) -> int:
        """Output samples the voice lasts, including its release."""
        r = v.region
        if v.sample is None:  # *silence: only exists to choke others
            return 0
        n_src = v.sample.data.shape[1]
        end_src = min(r.i("end", n_src - 1) + 1, n_src) if "end" in r.op else n_src
        natural = int(max(end_src - v.offset, 0) / v.ratio)
        loop_mode = r.op.get("loop_mode", "no_loop")
        loops = loop_mode in ("loop_continuous", "loop_sustain") and self._loop(v) is not None
        rel = int(max(self._eg(r, "release"), 0.001) * self.sr)
        stops = []
        if v.note_off is not None:
            stops.append(v.note_off - v.start + rel)
        if v.cut_at is not None:
            stops.append(v.cut_at - v.start + int(v.cut_time * self.sr) + 32)
        if loops:
            return max(min(stops), 0) if stops else natural
        return max(min([natural] + stops), 0)

    def _loop(self, v: _Voice) -> Optional[tuple[int, int]]:
        r = v.region
        if "loop_start" in r.op and "loop_end" in r.op:
            return (r.i("loop_start"), r.i("loop_end"))
        if "loopstart" in r.op and "loopend" in r.op:
            return (r.i("loopstart"), r.i("loopend"))
        return v.sample.loop if v.sample else None

    def _render_voice(self, v: _Voice, out: np.ndarray) -> None:
        length = self._voice_length(v)
        if length <= 0 or v.start >= out.shape[1]:
            return
        length = min(length, out.shape[1] - v.start)
        src = v.sample.data
        n_src = src.shape[1]
        if v.vibrato is not None:
            # Pitch wobble that fades in after the delay; same phase for every
            # layer of a note, so stacked instruments wobble together.
            t = np.arange(length, dtype=np.float64) / self.sr
            depth = v.vibrato.cents * np.clip((t - v.vibrato.delay) / max(v.vibrato.ramp, 1e-3), 0.0, 1.0)
            cents_t = depth * np.sin(2 * math.pi * v.vibrato.rate * np.maximum(t - v.vibrato.delay, 0.0))
            rates = v.ratio * np.power(2.0, cents_t / 1200.0)
            pos = v.offset + np.concatenate([[0.0], np.cumsum(rates[:-1])])
        else:
            pos = v.offset + np.arange(length, dtype=np.float64) * v.ratio
        loop = self._loop(v)
        loop_mode = v.region.op.get("loop_mode", "no_loop")
        if loop and loop_mode in ("loop_continuous", "loop_sustain"):
            ls, le = loop
            le = min(le, n_src - 1)
            if le > ls:
                span = le - ls + 1
                over = pos > le
                if loop_mode == "loop_sustain" and v.note_off is not None:
                    over &= np.arange(length) < (v.note_off - v.start)
                pos[over] = ls + np.mod(pos[over] - ls, span)
        valid = pos < n_src - 1
        if not valid.all():
            last = int(np.argmax(~valid))
            length = last
            pos = pos[:length]
            if length <= 0:
                return
        i0 = pos.astype(np.int64)
        frac = (pos - i0).astype(np.float32)
        audio = src[:, i0] * (1.0 - frac) + src[:, i0 + 1] * frac
        env = self._envelope(v, length) * v.gain
        audio *= env

        # Width (stereo spread) then equal-power-ish pan, as sfizz does.
        if v.width != 1.0:
            mid = (audio[0] + audio[1]) * 0.5
            side = (audio[0] - audio[1]) * 0.5 * v.width
            audio = np.vstack([mid + side, mid - side])
        if v.pan != 0.0:
            angle = (v.pan + 1.0) * math.pi / 4.0
            audio[0] *= math.cos(angle) * math.sqrt(2.0)
            audio[1] *= math.sin(angle) * math.sqrt(2.0)
        out[:, v.start:v.start + length] += audio

    def render(self, notes: list[Note], *, tail_seconds: float = 3.0) -> np.ndarray:
        """Render ``notes`` (seconds) to a ``(2, N)`` float32 buffer."""
        if not notes:
            return np.zeros((2, 0), dtype=np.float32)
        notes = sorted(notes, key=lambda n: (n.start, n.pitch))
        total = int((max(n.end for n in notes) + tail_seconds) * self.sr)

        # Event list: note-ons and note-offs, so first/legato/release triggers
        # know how many keys are held.
        events: list[tuple[float, int, Note]] = []
        for n in notes:
            events.append((n.start, 1, n))
            events.append((max(n.end, n.start + 0.005), 0, n))
        events.sort(key=lambda e: (e[0], e[1]))

        voices: list[_Voice] = []
        held: set[int] = set()
        for t, is_on, n in events:
            key = n.pitch + self.inst.note_offset
            vel = int(min(max(n.velocity, 1), 127))
            if is_on:
                for r in self._pick(key, vel, "attack", len(held)):
                    v = self._voice(r, key, vel, n.start, n.end)
                    if v is None:
                        continue
                    self._choke(voices, v)
                    self._limit_polyphony(voices, v)
                    voices.append(v)
                held.add(id(n))
            else:
                held.discard(id(n))
                for r in self._pick(key, vel, "release", len(held)):
                    v = self._voice(r, key, vel, n.end, None, held_seconds=n.end - n.start)
                    if v is not None:
                        self._choke(voices, v)
                        voices.append(v)

        total = max([total] + [v.start + self._voice_length(v) for v in voices])
        out = np.zeros((2, total), dtype=np.float32)
        for v in voices:
            if v.sample is not None:
                self._render_voice(v, out)
        return out

    def _choke(self, voices: list[_Voice], new: _Voice) -> None:
        g = new.region.group
        if not g:
            return
        for v in voices:
            if v.region.off_by == g and v is not new and v.start <= new.start:
                if v.cut_at is None or v.cut_at > new.start:
                    v.cut_at = new.start
                    mode = v.region.op.get("off_mode", "fast")
                    if mode == "normal":
                        v.cut_time = max(self._eg(v.region, "release"), 0.006)
                    elif mode == "time":
                        v.cut_time = max(v.region.f("off_time", 0.006), 0.001)
                    else:
                        v.cut_time = 0.006

    def _limit_polyphony(self, voices: list[_Voice], new: _Voice) -> None:
        limit = new.region.i("note_polyphony", 0)
        if limit <= 0:
            return
        same = [v for v in voices if v.key == new.key and v.region.group == new.region.group
                and (v.cut_at is None or v.cut_at > new.start)
                and v.start + self._voice_length(v) > new.start]
        selfmask = new.region.op.get("note_selfmask", "on") != "off"
        while len(same) >= limit:
            victim = same.pop(0)
            if selfmask and victim.velocity > new.velocity and len(same) + 1 >= limit:
                # Quieter hits don't kill louder ones; let the old one ring.
                continue
            victim.cut_at = new.start
            victim.cut_time = 0.03


def trigger_is_release(r: Region) -> bool:
    return r.trigger in ("release", "release_key")
