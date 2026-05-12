"""
Basic music generation utilities.
"""

import os
import numpy as np
import torch
import torchaudio
from typing import Optional, Tuple
import warnings

warnings.filterwarnings("ignore")


class BasicMusicGenerator:
    """Basic music generation utilities."""

    def __init__(self, device: Optional[str] = None):
        """
        Initialize music generator.

        Args:
            device: Device to use ('cpu', 'cuda', 'mps'). Auto-detects if None.
        """
        if device is None:
            if torch.backends.mps.is_available():
                device = "mps"
            elif torch.cuda.is_available():
                device = "cuda"
            else:
                device = "cpu"

        self.device = torch.device(device)
        print(f"Using device: {self.device}")

    def generate_sine_wave(self, frequency: float = 440.0, duration: float = 2.0,
                          sample_rate: int = 44100, amplitude: float = 0.5) -> np.ndarray:
        """
        Generate a simple sine wave.

        Args:
            frequency: Frequency in Hz
            duration: Duration in seconds
            sample_rate: Sample rate
            amplitude: Amplitude (0.0 to 1.0)

        Returns:
            Sine wave as numpy array
        """
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        sine_wave = amplitude * np.sin(2 * np.pi * frequency * t)

        # Convert to stereo
        stereo_wave = np.stack([sine_wave, sine_wave * 0.8], axis=0)

        return stereo_wave

    def generate_chord(self, frequencies: list, duration: float = 2.0,
                      sample_rate: int = 44100, amplitude: float = 0.3) -> np.ndarray:
        """
        Generate a chord from multiple frequencies.

        Args:
            frequencies: List of frequencies in Hz
            duration: Duration in seconds
            sample_rate: Sample rate
            amplitude: Amplitude (0.0 to 1.0)

        Returns:
            Chord as numpy array
        """
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

        # Generate each frequency component
        chord = np.zeros_like(t)
        for freq in frequencies:
            chord += amplitude * np.sin(2 * np.pi * freq * t)

        # Normalize to prevent clipping
        chord = chord / len(frequencies)

        # Convert to stereo
        stereo_chord = np.stack([chord, chord * 0.8], axis=0)

        return stereo_chord

    def generate_arpeggio(self, frequencies: list, duration: float = 4.0,
                         sample_rate: int = 44100, amplitude: float = 0.3) -> np.ndarray:
        """
        Generate an arpeggio (sequence of notes).

        Args:
            frequencies: List of frequencies in Hz
            duration: Duration in seconds
            sample_rate: Sample rate
            amplitude: Amplitude (0.0 to 1.0)

        Returns:
            Arpeggio as numpy array
        """
        note_duration = duration / len(frequencies)
        t_total = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        arpeggio = np.zeros_like(t_total)

        for i, freq in enumerate(frequencies):
            start_sample = int(i * note_duration * sample_rate)
            end_sample = int((i + 1) * note_duration * sample_rate)

            if end_sample > len(t_total):
                end_sample = len(t_total)

            note_length = end_sample - start_sample
            if note_length > 0:
                t_note = np.linspace(0, note_duration, note_length, endpoint=False)
                note = amplitude * np.sin(2 * np.pi * freq * t_note)

                # Apply envelope to avoid clicks
                envelope = np.ones_like(note)
                attack_samples = int(0.01 * sample_rate)  # 10ms attack
                release_samples = int(0.02 * sample_rate)  # 20ms release

                if attack_samples > 0:
                    envelope[:attack_samples] = np.linspace(0, 1, attack_samples)
                if release_samples > 0:
                    envelope[-release_samples:] = np.linspace(1, 0, release_samples)

                note = note * envelope
                arpeggio[start_sample:end_sample] = note

        # Convert to stereo
        stereo_arpeggio = np.stack([arpeggio, arpeggio * 0.8], axis=0)

        return stereo_arpeggio

    def add_reverb(self, audio: np.ndarray, sample_rate: int, decay: float = 1.0) -> np.ndarray:
        """
        Add simple reverb effect.

        Args:
            audio: Input audio
            sample_rate: Sample rate
            decay: Reverb decay time in seconds

        Returns:
            Audio with reverb
        """
        # Simple reverb using impulse response
        impulse_length = int(decay * sample_rate)
        impulse = np.exp(-np.linspace(0, 5, impulse_length))
        impulse = impulse / np.max(impulse)

        # Apply convolution to each channel
        if len(audio.shape) == 2:
            result = np.zeros_like(audio)
            for i in range(audio.shape[0]):
                result[i] = np.convolve(audio[i], impulse, mode='same')
        else:
            result = np.convolve(audio, impulse, mode='same')

        # Mix dry and wet signals
        wet_dry_mix = 0.3  # 30% wet, 70% dry
        result = wet_dry_mix * result + (1 - wet_dry_mix) * audio

        return result

    def generate_test_melody(self) -> Tuple[np.ndarray, int]:
        """
        Generate a simple test melody.

        Returns:
            Tuple of (audio_data, sample_rate)
        """
        sample_rate = 44100

        # C major scale frequencies (C4 to C5)
        c_major_freqs = [261.63, 293.66, 329.63, 349.23, 392.00, 440.00, 493.88, 523.25]

        # Generate arpeggio
        arpeggio = self.generate_arpeggio(
            frequencies=c_major_freqs[:4],  # C, E, G, C
            duration=4.0,
            sample_rate=sample_rate,
            amplitude=0.2
        )

        # Generate chord progression
        chord_progression = []
        chord_duration = 2.0

        # I - IV - V - I progression in C major
        chords = [
            [261.63, 329.63, 392.00],  # C major (C, E, G)
            [349.23, 440.00, 523.25],  # F major (F, A, C)
            [392.00, 493.88, 587.33],  # G major (G, B, D)
            [261.63, 329.63, 392.00],  # C major (C, E, G)
        ]

        for chord_freqs in chords:
            chord = self.generate_chord(
                frequencies=chord_freqs,
                duration=chord_duration,
                sample_rate=sample_rate,
                amplitude=0.15
            )
            chord_progression.append(chord)

        # Combine all parts
        total_duration = 4.0 + (len(chord_progression) * chord_duration)
        total_samples = int(total_duration * sample_rate)

        # Initialize output
        output = np.zeros((2, total_samples))

        # Add arpeggio (first 4 seconds)
        arpeggio_samples = arpeggio.shape[1]
        output[:, :arpeggio_samples] += arpeggio

        # Add chord progression (starting at 2 seconds)
        chord_start = 2 * sample_rate
        for i, chord in enumerate(chord_progression):
            start = chord_start + (i * chord_duration * sample_rate)
            end = start + chord.shape[1]

            if end <= total_samples:
                output[:, start:end] += chord

        # Normalize to prevent clipping
        peak = np.max(np.abs(output))
        if peak > 0:
            output = output / peak * 0.8  # Scale to 80% of max

        # Add reverb
        output = self.add_reverb(output, sample_rate, decay=0.5)

        return output, sample_rate


def test_generator():
    """Test music generator functionality."""
    generator = BasicMusicGenerator()

    # Create test directory
    test_dir = "data/outputs"
    os.makedirs(test_dir, exist_ok=True)

    # Generate test sounds
    sample_rate = 44100

    # 1. Generate sine wave
    print("Generating sine wave...")
    sine_wave = generator.generate_sine_wave(frequency=440.0, duration=2.0)
    sine_file = os.path.join(test_dir, "sine_a4.wav")

    # Save using torchaudio
    torchaudio.save(sine_file, torch.from_numpy(sine_wave), sample_rate)
    print(f"Saved sine wave to {sine_file}")

    # 2. Generate chord
    print("Generating C major chord...")
    c_major = [261.63, 329.63, 392.00]  # C4, E4, G4
    chord = generator.generate_chord(frequencies=c_major, duration=3.0)
    chord_file = os.path.join(test_dir, "c_major_chord.wav")
    torchaudio.save(chord_file, torch.from_numpy(chord), sample_rate)
    print(f"Saved chord to {chord_file}")

    # 3. Generate arpeggio
    print("Generating arpeggio...")
    arpeggio_freqs = [261.63, 329.63, 392.00, 523.25]  # C4, E4, G4, C5
    arpeggio = generator.generate_arpeggio(frequencies=arpeggio_freqs, duration=4.0)
    arpeggio_file = os.path.join(test_dir, "arpeggio.wav")
    torchaudio.save(arpeggio_file, torch.from_numpy(arpeggio), sample_rate)
    print(f"Saved arpeggio to {arpeggio_file}")

    # 4. Generate test melody
    print("Generating test melody...")
    melody, sr = generator.generate_test_melody()
    melody_file = os.path.join(test_dir, "test_melody.wav")
    torchaudio.save(melody_file, torch.from_numpy(melody), sr)
    print(f"Saved test melody to {melody_file}")

    print(f"\nAll test files saved to {test_dir}")
    return True


if __name__ == "__main__":
    print("Testing BasicMusicGenerator...")
    if test_generator():
        print("\nBasicMusicGenerator tests passed!")
        print("Check the 'data/outputs' directory for generated audio files.")
    else:
        print("BasicMusicGenerator tests failed!")