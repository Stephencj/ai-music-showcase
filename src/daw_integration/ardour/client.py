"""
Ardour DAW integration.

Two layers of integration:

1. **ArdourSessionBuilder** (always available) — assembles a directory of
   audio/MIDI files organized for easy drag-and-drop import into Ardour
   (or any DAW). No running Ardour instance required.

2. **ArdourOSCClient** (requires ``python-osc``) — send OSC messages to a
   running Ardour instance for transport control, track manipulation, etc.
   Install with: ``pip install python-osc``
"""

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session builder (no Ardour dependency)
# ---------------------------------------------------------------------------

@dataclass
class SessionTrack:
    """Metadata for one track in the session."""
    name: str
    track_type: str = "audio"       # "audio" or "midi"
    color: str = "#5b9bd5"
    files: list[Path] = field(default_factory=list)


class ArdourSessionBuilder:
    """Build a session directory ready for import into Ardour.

    Creates a folder structure like::

        my_session/
        ├── manifest.json       ← metadata (tempo, tracks, etc.)
        ├── audio/
        │   ├── Lead.wav
        │   └── Pad.wav
        └── midi/
            ├── Chords.mid
            └── Drums.mid

    This can be imported into Ardour by dragging files onto the timeline,
    or by using Session > Import.

    Example::

        builder = ArdourSessionBuilder("My AI Session", tempo=120)
        builder.add_audio_track("Lead", lead_audio, 44100)
        builder.add_midi_file("Chords", "path/to/chords.mid")
        session_dir = builder.export("data/outputs/sessions")
    """

    def __init__(
        self,
        session_name: str,
        tempo: float = 120.0,
        sample_rate: int = 44100,
        time_signature: tuple[int, int] = (4, 4),
    ):
        self.session_name = session_name
        self.tempo = tempo
        self.sample_rate = sample_rate
        self.time_signature = time_signature
        self.tracks: list[SessionTrack] = []
        self._audio_data: dict[str, tuple[np.ndarray, int]] = {}
        self._midi_sources: dict[str, Path] = {}

    def add_audio_track(
        self,
        name: str,
        audio: np.ndarray,
        sample_rate: Optional[int] = None,
        color: str = "#5b9bd5",
    ) -> "ArdourSessionBuilder":
        """Add a track with in-memory audio data.

        Args:
            name: Track name (also used as filename).
            audio: Audio array — shape (samples,) or (channels, samples).
            sample_rate: Sample rate. Defaults to session sample rate.
            color: Track color hex string.
        """
        sr = sample_rate or self.sample_rate
        self._audio_data[name] = (audio, sr)
        self.tracks.append(SessionTrack(name=name, track_type="audio", color=color))
        return self

    def add_audio_file(
        self,
        name: str,
        path: str | Path,
        color: str = "#5b9bd5",
    ) -> "ArdourSessionBuilder":
        """Add a track by copying an existing audio file.

        Args:
            name: Track name.
            path: Path to existing WAV/FLAC/etc file.
            color: Track color hex string.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")
        track = SessionTrack(name=name, track_type="audio", color=color)
        track.files.append(path)
        self.tracks.append(track)
        return self

    def add_midi_file(
        self,
        name: str,
        path: str | Path,
        color: str = "#70ad47",
    ) -> "ArdourSessionBuilder":
        """Add a MIDI track by copying an existing MIDI file.

        Args:
            name: Track name.
            path: Path to existing .mid file.
            color: Track color hex string.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"MIDI file not found: {path}")
        self._midi_sources[name] = path
        self.tracks.append(SessionTrack(name=name, track_type="midi", color=color))
        return self

    def add_rendered_stems(
        self,
        stems: dict[str, str | Path],
        *,
        color: str = "#5b9bd5",
    ) -> "ArdourSessionBuilder":
        """Add per-track audio stems produced by the render pipeline.

        Each stem file is added as its own audio track so it pre-loads
        when the session opens in Ardour.

        Args:
            stems: Mapping ``track_name → path-to-WAV``. Missing files
                are skipped with a warning.
            color: Track color (applied to all stems).
        """
        for name, path in stems.items():
            p = Path(path)
            if not p.exists():
                logger.warning("ardour: stem missing %s", p)
                continue
            self.add_audio_file(name, p, color=color)
        return self

    def export(self, output_dir: str | Path) -> Path:
        """Write the session directory to disk.

        Args:
            output_dir: Parent directory. Session folder is created inside.

        Returns:
            Path to the session directory.
        """
        output_dir = Path(output_dir)
        session_dir = output_dir / self.session_name.replace(" ", "_")
        audio_dir = session_dir / "audio"
        midi_dir = session_dir / "midi"

        audio_dir.mkdir(parents=True, exist_ok=True)
        midi_dir.mkdir(parents=True, exist_ok=True)

        written_files: list[str] = []

        # Write in-memory audio tracks
        for name, (audio, sr) in self._audio_data.items():
            wav_path = audio_dir / f"{name}.wav"
            # soundfile expects (samples, channels)
            data = audio
            if data.ndim == 2 and data.shape[0] < data.shape[1]:
                data = data.T
            sf.write(str(wav_path), data, sr)
            written_files.append(str(wav_path.relative_to(session_dir)))

        # Copy referenced audio files
        for track in self.tracks:
            for src in track.files:
                dst = audio_dir / f"{track.name}{src.suffix}"
                shutil.copy2(src, dst)
                written_files.append(str(dst.relative_to(session_dir)))

        # Copy MIDI files
        for name, src in self._midi_sources.items():
            dst = midi_dir / f"{name}.mid"
            shutil.copy2(src, dst)
            written_files.append(str(dst.relative_to(session_dir)))

        # Write manifest
        manifest = {
            "session_name": self.session_name,
            "created": datetime.now().isoformat(),
            "tempo": self.tempo,
            "sample_rate": self.sample_rate,
            "time_signature": list(self.time_signature),
            "tracks": [
                {"name": t.name, "type": t.track_type, "color": t.color}
                for t in self.tracks
            ],
            "files": written_files,
        }
        manifest_path = session_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

        print(f"Session exported: {session_dir}")
        print(f"  Tracks: {len(self.tracks)}")
        print(f"  Files:  {len(written_files)}")
        return session_dir


# ---------------------------------------------------------------------------
# OSC transport control (optional — requires python-osc)
# ---------------------------------------------------------------------------

class ArdourOSCClient:
    """Control a running Ardour instance via OSC.

    Requires the ``python-osc`` package (``pip install python-osc``).
    Enable OSC in Ardour: Edit → Preferences → Control Surfaces → OSC.

    Example::

        osc = ArdourOSCClient()   # localhost:3819 by default
        osc.play()
        osc.goto(8.0)
        osc.stop()
    """

    def __init__(self, host: str = "localhost", port: int = 3819):
        self.host = host
        self.port = port
        self._client = None

    def _ensure_connected(self):
        if self._client is not None:
            return
        try:
            from pythonosc.udp_client import SimpleUDPClient
        except ImportError:
            raise ImportError(
                "python-osc is required for OSC control. "
                "Install with: pip install python-osc"
            )
        self._client = SimpleUDPClient(self.host, self.port)
        logger.info(f"OSC client connected to {self.host}:{self.port}")

    def send(self, address: str, *args) -> None:
        """Send a raw OSC message."""
        self._ensure_connected()
        self._client.send_message(address, list(args))
        logger.debug(f"OSC → {address} {args}")

    # -- transport ----------------------------------------------------------

    def play(self) -> None:
        self.send("/transport_play")

    def stop(self) -> None:
        self.send("/transport_stop")

    def goto(self, seconds: float) -> None:
        """Move playhead to a position in seconds."""
        # Ardour OSC uses frames; assume 48 kHz session for frame count
        self.send("/locate", int(seconds * 48000), 1)

    def toggle_record(self) -> None:
        self.send("/rec_enable_toggle")

    def set_tempo(self, bpm: float) -> None:
        self.send("/set_tempo", bpm)

    # -- tracks -------------------------------------------------------------

    def set_track_gain(self, track_id: int, gain_db: float) -> None:
        """Set track gain in dB (track_id is 1-indexed)."""
        self.send(f"/strip/gain", track_id, gain_db)

    def mute_track(self, track_id: int, mute: bool = True) -> None:
        self.send(f"/strip/mute", track_id, int(mute))

    def solo_track(self, track_id: int, solo: bool = True) -> None:
        self.send(f"/strip/solo", track_id, int(solo))
