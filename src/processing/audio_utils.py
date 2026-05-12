"""
Audio processing utilities for AI music generation.
"""

import os
import numpy as np
import librosa
import soundfile as sf
from pydub import AudioSegment
from typing import Optional, Tuple, Union
import warnings

warnings.filterwarnings("ignore")


class AudioProcessor:
    """Audio processing utilities for loading, saving, and manipulating audio files."""

    def __init__(self, sample_rate: int = 44100, channels: int = 2):
        """
        Initialize audio processor.

        Args:
            sample_rate: Target sample rate for audio processing
            channels: Number of audio channels (1 for mono, 2 for stereo)
        """
        self.sample_rate = sample_rate
        self.channels = channels

    def load_audio(self, file_path: str, duration: Optional[float] = None) -> Tuple[np.ndarray, int]:
        """
        Load audio file.

        Args:
            file_path: Path to audio file
            duration: Duration to load in seconds (None for full file)

        Returns:
            Tuple of (audio_data, sample_rate)
        """
        try:
            audio, sr = librosa.load(file_path, sr=self.sample_rate, duration=duration, mono=False)

            # Ensure correct shape
            if len(audio.shape) == 1:
                # Mono audio
                if self.channels == 2:
                    # Convert mono to stereo
                    audio = np.stack([audio, audio], axis=0)
                else:
                    audio = audio.reshape(1, -1)
            else:
                # Multi-channel audio
                if audio.shape[0] > self.channels:
                    # Downmix to target channels
                    audio = audio[:self.channels, :]
                elif audio.shape[0] < self.channels:
                    # Upmix to target channels
                    if audio.shape[0] == 1 and self.channels == 2:
                        audio = np.stack([audio[0], audio[0]], axis=0)

            return audio, sr
        except Exception as e:
            raise ValueError(f"Error loading audio file {file_path}: {e}")

    def save_audio(self, audio: np.ndarray, file_path: str, sample_rate: Optional[int] = None):
        """
        Save audio data to file.

        Args:
            audio: Audio data as numpy array
            file_path: Path to save audio file
            sample_rate: Sample rate (uses instance sample_rate if None)
        """
        if sample_rate is None:
            sample_rate = self.sample_rate

        # Ensure correct shape
        if len(audio.shape) == 1:
            audio = audio.reshape(1, -1)

        # Convert to (samples, channels) format for soundfile
        if audio.shape[0] < audio.shape[1]:
            audio = audio.T

        try:
            sf.write(file_path, audio, sample_rate)
            print(f"Audio saved to {file_path}")
        except Exception as e:
            raise ValueError(f"Error saving audio to {file_path}: {e}")

    def convert_format(self, input_path: str, output_path: str, output_format: str = "wav"):
        """
        Convert audio file format.

        Args:
            input_path: Input audio file path
            output_path: Output audio file path
            output_format: Output format (wav, mp3, flac, etc.)
        """
        audio = AudioSegment.from_file(input_path)
        audio.export(output_path, format=output_format)
        print(f"Converted {input_path} to {output_path} ({output_format})")

    def normalize_audio(self, audio: np.ndarray, target_dB: float = -3.0) -> np.ndarray:
        """
        Normalize audio to target dB level.

        Args:
            audio: Audio data
            target_dB: Target dB level

        Returns:
            Normalized audio data
        """
        # Calculate current peak level in dB
        peak = np.max(np.abs(audio))
        if peak == 0:
            return audio

        current_dB = 20 * np.log10(peak)
        gain_dB = target_dB - current_dB
        gain_linear = 10 ** (gain_dB / 20)

        return audio * gain_linear

    def trim_silence(self, audio: np.ndarray, threshold_db: float = -40.0) -> np.ndarray:
        """
        Trim silence from beginning and end of audio.

        Args:
            audio: Audio data
            threshold_db: Silence threshold in dB

        Returns:
            Trimmed audio data
        """
        if len(audio.shape) == 2:
            # Use first channel for silence detection
            audio_mono = audio[0] if audio.shape[0] < audio.shape[1] else audio[:, 0]
        else:
            audio_mono = audio

        # Convert threshold to linear
        threshold = 10 ** (threshold_db / 20)

        # Find non-silent parts
        non_silent = np.where(np.abs(audio_mono) > threshold)[0]

        if len(non_silent) == 0:
            return audio

        start = non_silent[0]
        end = non_silent[-1]

        return audio[..., start:end]

    def extract_features(self, audio: np.ndarray, sample_rate: int) -> dict:
        """
        Extract audio features.

        Args:
            audio: Audio data
            sample_rate: Sample rate

        Returns:
            Dictionary of audio features
        """
        if len(audio.shape) == 2:
            # Use first channel for feature extraction
            audio_mono = audio[0] if audio.shape[0] < audio.shape[1] else audio[:, 0]
        else:
            audio_mono = audio

        features = {}

        # MFCCs
        mfccs = librosa.feature.mfcc(y=audio_mono, sr=sample_rate, n_mfcc=13)
        features['mfcc_mean'] = np.mean(mfccs, axis=1)
        features['mfcc_std'] = np.std(mfccs, axis=1)

        # Chroma features
        chroma = librosa.feature.chroma_stft(y=audio_mono, sr=sample_rate)
        features['chroma_mean'] = np.mean(chroma, axis=1)

        # Spectral features
        spectral_centroid = librosa.feature.spectral_centroid(y=audio_mono, sr=sample_rate)
        features['spectral_centroid_mean'] = np.mean(spectral_centroid)

        spectral_bandwidth = librosa.feature.spectral_bandwidth(y=audio_mono, sr=sample_rate)
        features['spectral_bandwidth_mean'] = np.mean(spectral_bandwidth)

        # Tempo
        tempo, _ = librosa.beat.beat_track(y=audio_mono, sr=sample_rate)
        # tempo can be a float or array, handle both cases
        if isinstance(tempo, (list, np.ndarray)) and len(tempo) > 0:
            features['tempo'] = tempo[0]
        else:
            features['tempo'] = float(tempo) if tempo is not None else 0.0

        # Zero crossing rate
        zcr = librosa.feature.zero_crossing_rate(audio_mono)
        features['zero_crossing_rate_mean'] = np.mean(zcr)

        return features


def test_audio_processor():
    """Test audio processor functionality."""
    processor = AudioProcessor()

    # Create test directory
    test_dir = "data/test"
    os.makedirs(test_dir, exist_ok=True)

    # Generate test audio
    duration = 2.0  # seconds
    sample_rate = 44100
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

    # Generate a simple sine wave
    frequency = 440  # A4 note
    audio = 0.5 * np.sin(2 * np.pi * frequency * t)

    # Convert to stereo
    audio_stereo = np.stack([audio, audio * 0.8], axis=0)

    # Save test audio
    test_file = os.path.join(test_dir, "test_sine.wav")
    processor.save_audio(audio_stereo, test_file, sample_rate)

    # Load and test
    loaded_audio, loaded_sr = processor.load_audio(test_file)
    print(f"Loaded audio shape: {loaded_audio.shape}, sample rate: {loaded_sr}")

    # Extract features
    features = processor.extract_features(loaded_audio, loaded_sr)
    print(f"Extracted features: {list(features.keys())}")

    # Clean up
    os.remove(test_file)
    os.rmdir(test_dir)

    return True


if __name__ == "__main__":
    print("Testing AudioProcessor...")
    if test_audio_processor():
        print("AudioProcessor tests passed!")
    else:
        print("AudioProcessor tests failed!")