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

# The CoreML EP fails on long sequences ("Error in dynamically resizing
# for sequence length"), so render a line in chunks: split on rests (seams
# fall in silence) and cap each chunk's frame count as a hard backstop.
# 1200 frames (~14 s) sits safely under the longest known-good single pass.
_CHUNK_GAP = 0.25          # a rest this long (s) starts a fresh chunk
_MAX_CHUNK_FRAMES = 1200


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

        self._acoustic_path = self.vb / "dsacoustic" / "acoustic.onnx"
        self._vocoder_path = self.vb / "dsvocoder" / "tgm_hifigan.onnx"
        self._acoustic = _session(self._acoustic_path)
        self._vocoder = _session(self._vocoder_path)
        self._cpu_only = False   # flips on once CoreML fails a run (see _infer)

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

        self._spk = np.zeros(256, np.float32)
        self.speaker = ""
        self.set_speaker(speaker)
        self._g2p = None

    def set_speaker(self, speaker: str) -> "StudioEngine":
        """Swap the speaker embedding (the ONNX sessions are speaker-
        independent, so one compiled engine serves every voice)."""
        emb_path = self.vb / "dsacoustic" / f"{speaker}.emb"
        if not emb_path.exists():
            cands = sorted((self.vb / "dsacoustic").glob("*.emb"))
            emb_path = cands[0] if cands else None
        self._spk = (np.fromfile(str(emb_path), dtype=np.float32) if emb_path else np.zeros(256, np.float32))
        self.speaker = emb_path.stem if emb_path else ""
        return self

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
        # Build chunks of (tokens, durations, f0) split on rests / a frame cap
        # so each ONNX inference stays short enough for the CoreML EP. Each
        # chunk records its absolute start time so we can overlay it back onto
        # the song timeline (the silence between chunks is just the buffer).
        chunks: list[dict] = []
        cur: dict | None = None
        prev_end = 0.0

        def _flush():
            nonlocal cur
            if cur and cur["tokens"]:
                chunks.append(cur)
            cur = None

        for seg in segments:
            gap = seg["start"] - prev_end
            if cur is not None and gap > _CHUNK_GAP:
                _flush()
            note_time = seg["start"]
            groups = self._syllabify(self._phonemes(seg["text"]), len(seg["notes"]))
            for ni, ((midi, ndur), group) in enumerate(zip(seg["notes"], groups)):
                nf = max(1, round(ndur / self.frame_sec))
                if cur is not None and len(cur["f0"]) + nf > _MAX_CHUNK_FRAMES:
                    _flush()                                   # cap hit → hard split
                if cur is None:
                    cur = {"start": note_time, "tokens": [], "durs": [], "f0": []}
                elif ni == 0 and gap > 0.03:
                    # short rest before this segment → keep timing with an SP
                    g = max(1, round(gap / self.frame_sec))
                    cur["tokens"].append(self._sp); cur["durs"].append(g)
                    cur["f0"].extend([0.0] * g)
                hz = float(midi_to_hz(midi))
                # phoneme tokens + per-phoneme frame durations. A syllable
                # with more phonemes than the note has frames (consonant
                # clusters on a short note) makes _allocate return MORE frames
                # than nf, so derive the F0 length from the allocation — the
                # mel (durations) and f0 lengths must agree or inference fails.
                alloc = self._allocate(group, nf)
                for ph, fr in alloc:
                    cur["tokens"].append(self.ph2id.get(ph, self._fallback_vowel))
                    cur["durs"].append(fr)
                note_nf = sum(fr for _, fr in alloc)
                # per-frame F0: hit the note cleanly (no scoop — constant
                # glides read as out-of-tune "searching"). Add gentle vibrato
                # on sustained notes for a natural, confident voice.
                note_f0 = np.full(note_nf, hz, dtype=float)
                if ndur >= 0.5 and note_nf > 8:
                    tt = np.arange(note_nf) * self.frame_sec
                    ramp = np.clip((tt - 0.2) / 0.25, 0.0, 1.0)   # ease vibrato in after 0.2 s
                    semis = 0.22 * np.sin(2 * np.pi * 5.5 * tt) * ramp
                    note_f0 = hz * (2.0 ** (semis / 12.0))
                cur["f0"].extend(note_f0.tolist())
                prev_end = note_time + ndur
                note_time = prev_end
        _flush()

        if not chunks:
            return np.zeros(0, dtype=np.float32), self.sr

        total = prev_end + 0.3
        out = np.zeros(int(total * self.sr) + self.sr, dtype=np.float32)
        fade = max(1, int(0.002 * self.sr))                    # 2 ms edges → no seam clicks
        for ch in chunks:
            nf = len(ch["f0"])
            wave = self._infer(np.array(ch["tokens"], np.int64), np.array(ch["durs"], np.int64),
                               np.array(ch["f0"], np.float32), nf)
            if wave.size > 2 * fade:
                wave[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
                wave[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
            i0 = int(ch["start"] * self.sr)
            i1 = min(len(out), i0 + len(wave))
            if i1 > i0:
                out[i0:i1] += wave[: i1 - i0]
        out = out[: int(total * self.sr)]

        if sr != self.sr and out.size:
            import librosa
            out = librosa.resample(out, orig_sr=self.sr, target_sr=sr)
            return out.astype(np.float32), sr
        return out.astype(np.float32), self.sr

    def _force_cpu(self) -> None:
        """Rebuild both ONNX sessions on CPU. The CoreML EP can fail at *run*
        time (not just init) — e.g. 'dynamically resizing for sequence length'
        when its compile cache is unwritable / disk is tight — so we drop to
        CPU once and stay there for the rest of the render (reliable, slower)."""
        import onnxruntime as ort
        self._acoustic = ort.InferenceSession(str(self._acoustic_path), providers=["CPUExecutionProvider"])
        self._vocoder = ort.InferenceSession(str(self._vocoder_path), providers=["CPUExecutionProvider"])
        self._cpu_only = True

    def _run(self, tokens, durs, f0, n_frames) -> np.ndarray:
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

    def _infer(self, tokens, durs, f0, n_frames) -> np.ndarray:
        try:
            return self._run(tokens, durs, f0, n_frames)
        except Exception as exc:  # noqa: BLE001
            if self._cpu_only:
                raise
            logger.warning("studio inference failed on CoreML (%s) — falling back to CPU", exc)
            self._force_cpu()
            return self._run(tokens, durs, f0, n_frames)

    # Per-segment path isn't used (render_line handles the whole line), but
    # satisfy the interface.
    def render_segment(self, text: str, notes: list[tuple[int, float]], sr: int) -> np.ndarray:
        audio, _ = self.render_line([{"text": text, "notes": notes, "start": 0.0}], sr)
        return audio
