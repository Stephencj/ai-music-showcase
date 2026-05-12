#!/usr/bin/env python3
"""
MIDI generation and processing example.

Demonstrates MIDI generation, manipulation, and conversion to audio.
Supports various MIDI generation approaches including rule-based,
Magenta (if available), and simple algorithmic composition.
"""
import argparse
import logging
import sys
import random
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)

class MIDIGenerator:
    """Base class for MIDI generation."""

    def __init__(self, tempo: int = 120, time_signature: Tuple[int, int] = (4, 4)):
        self.tempo = tempo
        self.time_signature = time_signature
        self.notes = []

    def generate(self, length_bars: int = 8) -> List[Dict[str, Any]]:
        """Generate MIDI notes."""
        raise NotImplementedError

    def save_midi(self, filepath: Path):
        """Save generated notes to MIDI file."""
        try:
            from mido import MidiFile, MidiTrack, Message, MetaMessage

            mid = MidiFile()
            track = MidiTrack()
            mid.tracks.append(track)

            # Set tempo
            microseconds_per_beat = int(60000000 / self.tempo)
            track.append(MetaMessage('set_tempo', tempo=microseconds_per_beat))

            # Set time signature
            track.append(MetaMessage('time_signature',
                                     numerator=self.time_signature[0],
                                     denominator=self.time_signature[1]))

            # Add notes
            for note in self.notes:
                track.append(Message('note_on',
                                     note=note['pitch'],
                                     velocity=note['velocity'],
                                     time=note['start']))
                track.append(Message('note_off',
                                     note=note['pitch'],
                                     velocity=0,
                                     time=note['duration']))

            mid.save(str(filepath))
            logger.info(f"MIDI file saved: {filepath}")
            return True

        except ImportError:
            logger.error("mido not installed.")
            logger.info("Install with: pip install mido")
            return False

class RuleBasedMIDIGenerator(MIDIGenerator):
    """Rule-based MIDI generator for simple compositions."""

    def __init__(self, key: str = "C", scale: str = "major", **kwargs):
        super().__init__(**kwargs)
        self.key = key
        self.scale = scale
        self.scale_notes = self._get_scale_notes(key, scale)

    def _get_scale_notes(self, key: str, scale: str) -> List[int]:
        """Get MIDI note numbers for a given key and scale."""
        # MIDI note numbers for C major scale (starting at C4 = 60)
        c_major = [60, 62, 64, 65, 67, 69, 71, 72]  # C4 to C5

        # Map for different keys (simplified)
        key_map = {
            "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4,
            "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9,
            "A#": 10, "B": 11
        }

        # Adjust for key
        key_offset = key_map.get(key, 0)
        scale_notes = [note + key_offset for note in c_major]

        # Adjust for minor scale
        if scale.lower() == "minor":
            # Convert major to natural minor (lower 3rd, 6th, 7th)
            scale_notes = [
                scale_notes[0],  # 1
                scale_notes[1],  # 2
                scale_notes[2] - 1,  # b3
                scale_notes[3],  # 4
                scale_notes[4],  # 5
                scale_notes[5] - 1,  # b6
                scale_notes[6] - 1,  # b7
                scale_notes[7]  # 8
            ]

        return scale_notes

    def generate_chord_progression(self, progression: List[str] = None) -> List[Dict[str, Any]]:
        """Generate chord progression."""
        if progression is None:
            progression = ["I", "IV", "V", "I"]  # Basic pop progression

        # Chord definitions (simplified - triad chords)
        chord_map = {
            "I": [0, 2, 4],    # Tonic
            "ii": [1, 3, 5],   # Supertonic
            "iii": [2, 4, 6],  # Mediant
            "IV": [3, 5, 7],   # Subdominant
            "V": [4, 6, 0],    # Dominant (with wrap-around)
            "vi": [5, 7, 1],   # Submediant
            "vii°": [6, 0, 2], # Leading tone
        }

        notes = []
        ticks_per_bar = 480 * self.time_signature[0]  # Assuming 480 ticks per quarter note

        for bar, chord_symbol in enumerate(progression):
            if chord_symbol not in chord_map:
                logger.warning(f"Unknown chord symbol: {chord_symbol}, using I")
                chord_indices = chord_map["I"]
            else:
                chord_indices = chord_map[chord_symbol]

            # Get actual MIDI notes for chord
            chord_notes = [self.scale_notes[i] for i in chord_indices]

            # Add chord notes
            start_ticks = bar * ticks_per_bar
            for note_pitch in chord_notes:
                notes.append({
                    'pitch': note_pitch,
                    'velocity': 80,
                    'start': start_ticks,
                    'duration': ticks_per_bar
                })

        self.notes = notes
        return notes

    def generate_melody(self, length_bars: int = 8) -> List[Dict[str, Any]]:
        """Generate simple melody."""
        notes = []
        ticks_per_bar = 480 * self.time_signature[0]
        ticks_per_beat = 480

        # Possible rhythm patterns (in beats)
        rhythm_patterns = [
            [1, 1, 1, 1],  # Quarter notes
            [2, 2],        # Half notes
            [1, 0.5, 0.5, 1],  # Quarter, two eighths, quarter
            [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],  # All eighth notes
        ]

        current_tick = 0
        bar = 0

        while bar < length_bars:
            # Choose random rhythm pattern
            rhythm = random.choice(rhythm_patterns)

            for beat_value in rhythm:
                if random.random() > 0.3:  # 70% chance to play a note
                    # Choose random note from scale
                    pitch = random.choice(self.scale_notes)
                    velocity = random.randint(60, 100)

                    duration_ticks = int(beat_value * ticks_per_beat)

                    notes.append({
                        'pitch': pitch,
                        'velocity': velocity,
                        'start': current_tick,
                        'duration': duration_ticks
                    })

                current_tick += int(beat_value * ticks_per_beat)

            bar += 1

            # Reset tick counter if we exceed bar length
            if current_tick >= (bar + 1) * ticks_per_bar:
                current_tick = bar * ticks_per_bar

        self.notes = notes
        return notes

class MIDIToAudioConverter:
    """Convert MIDI to audio using soundfonts or synthesizers."""

    def __init__(self, soundfont_path: Optional[Path] = None):
        self.soundfont_path = soundfont_path

    def convert(self, midi_path: Path, output_path: Path,
                sample_rate: int = 44100) -> bool:
        """Convert MIDI file to audio."""
        try:
            import pretty_midi
            import soundfile as sf
            import numpy as np

            logger.info(f"Converting MIDI to audio: {midi_path}")

            # Load MIDI file
            midi_data = pretty_midi.PrettyMIDI(str(midi_path))

            # Synthesize audio
            audio = midi_data.synthesize(sample_rate=sample_rate)

            # Save audio
            sf.write(str(output_path), audio, sample_rate)
            logger.info(f"Audio saved: {output_path}")

            return True

        except ImportError as e:
            logger.error(f"Required packages not installed: {e}")
            logger.info("Install with: pip install pretty_midi soundfile numpy")
            return False
        except Exception as e:
            logger.error(f"Failed to convert MIDI to audio: {e}")
            return False

def demonstrate_midi_workflow(output_dir: Path):
    """Demonstrate complete MIDI workflow."""
    logger.info("Demonstrating MIDI generation workflow...")

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Generate chord progression
        logger.info("1. Generating chord progression...")
        chord_gen = RuleBasedMIDIGenerator(
            key="C",
            scale="major",
            tempo=120,
            time_signature=(4, 4)
        )

        progression = ["I", "V", "vi", "IV"]  # Common pop progression
        chords = chord_gen.generate_chord_progression(progression)

        # Save chord progression MIDI
        chords_midi = output_dir / "chord_progression.mid"
        chord_gen.save_midi(chords_midi)

        # 2. Generate melody
        logger.info("2. Generating melody...")
        melody_gen = RuleBasedMIDIGenerator(
            key="C",
            scale="major",
            tempo=120,
            time_signature=(4, 4)
        )

        melody = melody_gen.generate_melody(length_bars=8)

        # Save melody MIDI
        melody_midi = output_dir / "melody.mid"
        melody_gen.save_midi(melody_midi)

        # 3. Convert MIDI to audio (if possible)
        logger.info("3. Converting MIDI to audio...")
        converter = MIDIToAudioConverter()

        chords_audio = output_dir / "chord_progression.wav"
        melody_audio = output_dir / "melody.wav"

        # Try to convert
        chords_converted = converter.convert(chords_midi, chords_audio)
        melody_converted = converter.convert(melody_midi, melody_audio)

        if chords_converted and melody_converted:
            logger.info("MIDI to audio conversion successful")
        else:
            logger.warning("MIDI to audio conversion failed or not available")

        logger.info("\nGenerated files:")
        logger.info(f"  Chord progression MIDI: {chords_midi}")
        logger.info(f"  Melody MIDI: {melody_midi}")
        if chords_converted:
            logger.info(f"  Chord progression audio: {chords_audio}")
        if melody_converted:
            logger.info(f"  Melody audio: {melody_audio}")

        return True

    except Exception as e:
        logger.error(f"Error during MIDI workflow: {e}")
        return False

def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="MIDI generation and processing"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/outputs/midi"),
        help="Output directory for generated files"
    )
    parser.add_argument(
        "--key",
        default="C",
        help="Musical key (C, C#, D, etc.)"
    )
    parser.add_argument(
        "--scale",
        default="major",
        choices=["major", "minor"],
        help="Musical scale"
    )
    parser.add_argument(
        "--tempo",
        type=int,
        default=120,
        help="Tempo in BPM"
    )
    parser.add_argument(
        "--chords",
        action="store_true",
        help="Generate chord progression"
    )
    parser.add_argument(
        "--melody",
        action="store_true",
        help="Generate melody"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run complete workflow demonstration"
    )
    parser.add_argument(
        "--convert",
        type=Path,
        help="Convert MIDI file to audio"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info("MIDI Generation and Processing")
    logger.info("=" * 50)

    try:
        if args.demo:
            # Run demonstration
            success = demonstrate_midi_workflow(args.output_dir)
            sys.exit(0 if success else 1)

        elif args.convert:
            # Convert MIDI to audio
            converter = MIDIToAudioConverter()
            output_path = args.output_dir / f"{args.convert.stem}.wav"
            success = converter.convert(args.convert, output_path)
            sys.exit(0 if success else 1)

        else:
            # Generate specific content
            generator = RuleBasedMIDIGenerator(
                key=args.key,
                scale=args.scale,
                tempo=args.tempo
            )

            output_dir = args.output_dir
            output_dir.mkdir(parents=True, exist_ok=True)

            if args.chords:
                logger.info("Generating chord progression...")
                progression = ["I", "IV", "V", "I"]
                generator.generate_chord_progression(progression)

                output_path = output_dir / f"chords_{args.key}_{args.scale}.mid"
                generator.save_midi(output_path)
                logger.info(f"Chord progression saved: {output_path}")

            if args.melody:
                logger.info("Generating melody...")
                generator.generate_melody(length_bars=8)

                output_path = output_dir / f"melody_{args.key}_{args.scale}.mid"
                generator.save_midi(output_path)
                logger.info(f"Melody saved: {output_path}")

            if not args.chords and not args.melody:
                logger.info("No generation type specified.")
                logger.info("Use --chords to generate chord progression")
                logger.info("Use --melody to generate melody")
                logger.info("Use --demo for complete workflow demonstration")

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()