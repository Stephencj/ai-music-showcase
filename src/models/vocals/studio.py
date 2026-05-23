"""Studio vocal engine — local DiffSinger SVS (ONNX) for real singing.

Runs the voicebank's ``acoustic.onnx`` → ``tgm_hifigan.onnx`` (vocoder)
directly in "manual" mode: we supply phoneme tokens, per-phoneme frame
durations, and an F0 curve derived from the melody — so no duration /
pitch predictors are needed. Phonemes come from g2p_en (ARPABET, mapped
to the voicebank's lowercase phoneme set).

Voicebank: a DiffSinger OpenUTAU bank unzipped under
``data/models/diffsinger/tiger_vb`` (acoustic + vocoder ONNX + phonemes.txt
+ a speaker .emb). Models are CC BY-NC (personal use).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .engine import VocalEngine, midi_to_hz

logger = logging.getLogger("ai_music_studio.vocals.studio")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VB = PROJECT_ROOT / "data" / "models" / "diffsinger" / "tiger_vb"

# ARPABET monophthong/diphthong vowels (lowercased to the tiger set).
_VOWELS = {"aa", "ae", "ah", "ao", "aw", "ay", "eh", "er", "ey", "ih",
           "iy", "ow", "oy", "uh", "uw", "ax"}


def available(vb_dir: Path = DEFAULT_VB) -> bool:
    return (vb_dir / "dsacoustic" / "acoustic.onnx").exists() and \
           (vb_dir / "dsvocoder" / "tgm_hifigan.onnx").exists()


def list_speakers(vb_dir: Path = DEFAULT_VB) -> list[str]:
    """Selectable studio voices = the voicebank's speaker embeddings (.emb)."""
    try:
        return sorted(p.stem for p in (vb_dir / "dsacoustic").glob("*.emb"))
    except Exception:  # noqa: BLE001
        return []


class StudioEngine(VocalEngine):
    name = "studio"

    def __init__(self, vb_dir: Path | str = DEFAULT_VB, speaker: str = "tiger_fresh",
                 steps: int = 20) -> None:
        import onnxruntime as ort
        import yaml

        self.vb = Path(vb_dir)
        if not available(self.vb):
            raise FileNotFoundError(f"DiffSinger voicebank not found at {self.vb}")

        def _session(path: Path):
            # CoreML accelerates this on Apple Silicon, but its model-compile
            # step writes to a cache and fails with an I/O error when disk is
            # tight — fall back to CPU so a render never hard-fails.
            avail = ort.get_available_providers()
            if "CoreMLExecutionProvider" in avail:
                try:
                    return ort.InferenceSession(str(path), providers=["CoreMLExecutionProvider", "CPUExecutionProvider"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("CoreML init failed for %s (%s) — CPU only", path.name, exc)
            return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])

        self._acoustic = _session(self.vb / "dsacoustic" / "acoustic.onnx")
        self._vocoder = _session(self.vb / "dsvocoder" / "tgm_hifigan.onnx")

        cfg = yaml.safe_load(open(self.vb / "dsacoustic" / "dsconfig.yaml"))
        self.sr = int(cfg.get("sample_rate", 44100))
        self.hop = int(cfg.get("hop_size", 512))
        self.frame_sec = self.hop / self.sr
        self.max_depth = float(cfg.get("max_depth", 1.0))
        self.steps = int(steps)

        phs = (self.vb / "dsacoustic" / "phonemes.txt").read_text().split()
        self.ph2id = {p: i for i, p in enumerate(phs)}
        self._sp = self.ph2id.get("SP", 2)
        self._fallback_vowel = self.ph2id.get("ax", self.ph2id.get("ah", 3))

        # phoneme → articulation type (for natural consonant lengths)
        self.ph_type: dict[str, str] = {}
        try:
            dd = yaml.safe_load(open(self.vb / "dsdur" / "dsdict-en.yaml"))
            for s in dd.get("symbols", []):
                self.ph_type[str(s["symbol"])] = str(s.get("type"))
        except Exception:  # noqa: BLE001
            pass

        emb_path = self.vb / "dsacoustic" / f"{speaker}.emb"
        if not emb_path.exists():
            cands = sorted((self.vb / "dsacoustic").glob("*.emb"))
            emb_path = cands[0] if cands else None
        self._spk = (np.fromfile(str(emb_path), dtype=np.float32) if emb_path else np.zeros(256, np.float32))
        self._g2p = None

    # -- phonemes ----------------------------------------------------------
    def _phonemes(self, word: str) -> list[str]:
        if self._g2p is None:
            import nltk
            for res in ("averaged_perceptron_tagger_eng", "cmudict", "averaged_perceptron_tagger"):
                try:
                    nltk.download(res, quiet=True)
                except Exception:  # noqa: BLE001
                    pass
            from g2p_en import G2p
            self._g2p = G2p()
        out = []
        for tok in self._g2p(word):
            t = "".join(c for c in tok if c.isalpha()).lower()
            if t and t in self.ph2id:
                out.append(t)
        return out or ["ax"]

    @staticmethod
    def _syllabify(phs: list[str], n_groups: int) -> list[list[str]]:
        """Split phonemes into syllable groups (one vowel each), then
        reconcile the count to ``n_groups`` notes."""
        groups: list[list[str]] = []
        cur: list[str] = []
        for p in phs:
            cur.append(p)
            if p in _VOWELS:
                groups.append(cur)
                cur = []
        if cur:
            (groups[-1].extend(cur) if groups else groups.append(cur))
        if not groups:
            groups = [phs or ["ax"]]
        # reconcile to n_groups
        while len(groups) > n_groups:                 # merge tail
            groups[-2].extend(groups.pop())
        while len(groups) < n_groups:                 # sustain last vowel (melisma)
            groups.append([next((p for p in reversed(groups[-1]) if p in _VOWELS), groups[-1][-1])])
        return groups

    def _cons_frames(self, ph: str) -> int:
        """Natural-ish consonant length in frames (~12 ms/frame) by type."""
        t = self.ph_type.get(ph, "")
        if t == "stop":
            return 2                                   # ~23 ms — plosive
        if t in ("fricative", "affricate"):
            return 5                                   # ~58 ms — sustained noise
        if t in ("nasal", "liquid", "approximant", "semivowel", "glide"):
            return 4
        return 3

    def _allocate(self, group: list[str], n_frames: int) -> list[tuple[str, int]]:
        n_frames = max(n_frames, len(group))
        vows = [p for p in group if p in _VOWELS] or [group[-1]]
        cons_total = sum(self._cons_frames(p) for p in group if p not in _VOWELS)
        v_fr = max(2, (n_frames - cons_total) // len(vows))
        alloc = [[p, (v_fr if p in _VOWELS else self._cons_frames(p))] for p in group]
        diff = n_frames - sum(f for _, f in alloc)
        # absorb the leftover into the (last) vowel so sustains land on the note
        for i in range(len(alloc) - 1, -1, -1):
            if alloc[i][0] in _VOWELS:
                alloc[i][1] = max(1, alloc[i][1] + diff); break
        else:
            alloc[-1][1] = max(1, alloc[-1][1] + diff)
        return [(p, f) for p, f in alloc]

    # -- full-line render (interface used by render_lead_vocal) ------------
    def render_line(self, segments: list[dict], sr: int) -> tuple[np.ndarray, int]:
        tokens: list[int] = []
        durs: list[int] = []
        f0: list[float] = []
        prev_end = 0.0
        prev_hz = 0.0
        for seg in segments:
            gap = seg["start"] - prev_end
            if gap > 0.03:
                g = max(1, round(gap / self.frame_sec))
                tokens.append(self._sp); durs.append(g); f0.extend([0.0] * g)
                prev_hz = 0.0
            groups = self._syllabify(self._phonemes(seg["text"]), len(seg["notes"]))
            for (midi, ndur), group in zip(seg["notes"], groups):
                nf = max(1, round(ndur / self.frame_sec))
                hz = float(midi_to_hz(midi))
                # phoneme tokens + per-phoneme frame durations (sum == nf)
                for ph, fr in self._allocate(group, nf):
                    tokens.append(self.ph2id.get(ph, self._fallback_vowel))
                    durs.append(fr)
                # per-frame F0 for this note: a short glide (portamento) from
                # the previous pitch, then hold — sung note transitions, not steps.
                glide = min(4, nf // 3) if prev_hz > 0 else 0
                if glide > 0:
                    f0.extend(np.linspace(prev_hz, hz, glide, endpoint=False).tolist())
                f0.extend([hz] * (nf - glide))
                prev_hz = hz
            prev_end = seg["start"] + sum(d for _, d in seg["notes"])

        if not tokens:
            return np.zeros(0, dtype=np.float32), self.sr
        n_frames = len(f0)
        wave = self._infer(np.array(tokens, np.int64), np.array(durs, np.int64),
                           np.array(f0, np.float32), n_frames)
        if sr != self.sr and wave.size:
            import librosa
            wave = librosa.resample(wave, orig_sr=self.sr, target_sr=sr)
            return wave.astype(np.float32), sr
        return wave.astype(np.float32), self.sr

    def _infer(self, tokens, durs, f0, n_frames) -> np.ndarray:
        spk = np.tile(self._spk, (n_frames, 1))[None].astype(np.float32)
        mel = self._acoustic.run(["mel"], {
            "tokens": tokens[None],
            "durations": durs[None],
            "f0": f0[None],
            "gender": np.zeros((1, n_frames), np.float32),
            "velocity": np.ones((1, n_frames), np.float32),
            "spk_embed": spk,
            "depth": np.array(self.max_depth, np.float32),
            "steps": np.array(self.steps, np.int64),
        })[0]
        wave = self._vocoder.run(["waveform"], {"mel": mel, "f0": f0[None]})[0]
        return np.asarray(wave).reshape(-1)

    # Per-segment path isn't used (render_line handles the whole line), but
    # satisfy the interface.
    def render_segment(self, text: str, notes: list[tuple[int, float]], sr: int) -> np.ndarray:
        audio, _ = self.render_line([{"text": text, "notes": notes, "start": 0.0}], sr)
        return audio
