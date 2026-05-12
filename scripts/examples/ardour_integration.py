#!/usr/bin/env python3
"""
Ardour DAW integration example.

Demonstrates how to integrate with Ardour DAW using OSC (Open Sound Control).
"""
import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional, List, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)

class ArdourClient:
    """Client for Ardour DAW integration using OSC."""

    def __init__(self, host: str = "localhost", port: int = 3819):
        """
        Initialize Ardour client.

        Args:
            host: Ardour host address
            port: Ardour OSC port (default: 3819)
        """
        self.host = host
        self.port = port
        self.client = None

    def connect(self):
        """Connect to Ardour OSC server."""
        try:
            from pythonosc import udp_client
            self.client = udp_client.SimpleUDPClient(self.host, self.port)
            logger.info(f"Connected to Ardour at {self.host}:{self.port}")
            return True
        except ImportError:
            logger.error("python-osc not installed.")
            logger.info("Install with: pip install python-osc")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to Ardour: {e}")
            return False

    def send_osc(self, address: str, *args):
        """Send OSC message to Ardour."""
        if self.client is None:
            if not self.connect():
                return False

        try:
            self.client.send_message(address, args)
            logger.debug(f"Sent OSC: {address} {args}")
            return True
        except Exception as e:
            logger.error(f"Failed to send OSC message: {e}")
            return False

    def create_session(self, session_name: str, sample_rate: int = 44100,
                       bit_depth: int = 24, tempo: float = 120.0):
        """Create new Ardour session."""
        logger.info(f"Creating session: {session_name}")

        # Note: Ardour doesn't have direct OSC command for session creation
        # This would typically be done via Ardour's CLI or GUI
        # For demonstration, we'll send session-related commands

        # Set session properties
        self.send_osc("/ardour/set_tempo", tempo)
        self.send_osc("/ardour/set_timecode_fps", 30.0)  # 30 FPS timecode

        logger.info(f"Session '{session_name}' setup commands sent")
        return True

    def create_track(self, track_name: str, track_type: str = "audio",
                     channels: int = 2, color: str = "blue"):
        """Create new track in Ardour."""
        logger.info(f"Creating {track_type} track: {track_name}")

        # Create track
        self.send_osc("/ardour/new_track", track_type, track_name, channels)

        # Set track color (if supported)
        self.send_osc("/ardour/set_track_color", track_name, color)

        # Arm track for recording (if audio track)
        if track_type == "audio":
            self.send_osc("/ardour/arm_track", track_name, 1)

        logger.info(f"Track '{track_name}' created and configured")
        return True

    def import_audio(self, audio_path: Path, track_name: str,
                     position: float = 0.0, gain: float = 1.0):
        """Import audio file into Ardour track."""
        if not audio_path.exists():
            logger.error(f"Audio file not found: {audio_path}")
            return False

        logger.info(f"Importing audio: {audio_path} to track '{track_name}'")

        # Import audio file
        self.send_osc(
            "/ardour/import",
            str(audio_path),
            track_name,
            position,
            gain
        )

        logger.info(f"Audio imported to position {position}s with gain {gain}")
        return True

    def set_transport(self, state: str, position: float = 0.0):
        """Control Ardour transport (play, stop, record)."""
        states = ["stop", "play", "record", "loop"]

        if state not in states:
            logger.error(f"Invalid transport state: {state}. Must be one of {states}")
            return False

        logger.info(f"Setting transport: {state} at position {position}s")

        # Set transport state
        self.send_osc("/ardour/transport", state)

        # Set transport position if specified
        if position > 0:
            self.send_osc("/ardour/goto", position)

        return True

    def add_marker(self, name: str, position: float, color: str = "red"):
        """Add marker at specified position."""
        logger.info(f"Adding marker '{name}' at {position}s")

        self.send_osc("/ardour/add_marker", name, position, color)
        return True

    def get_track_list(self) -> List[str]:
        """Get list of tracks in current session."""
        # Note: This requires Ardour to send OSC back, which is more complex
        # For demonstration, we'll return a mock list
        logger.info("Getting track list (mock implementation)")

        # In real implementation, this would query Ardour via OSC
        # For now, return empty list
        return []

    def disconnect(self):
        """Disconnect from Ardour."""
        logger.info("Disconnecting from Ardour")
        self.client = None
        return True

def test_ardour_connection(host: str, port: int) -> bool:
    """Test connection to Ardour."""
    client = ArdourClient(host, port)

    logger.info("Testing Ardour connection...")

    if not client.connect():
        logger.error("Failed to connect to Ardour")
        return False

    # Send test ping
    success = client.send_osc("/ardour/ping", "test")

    if success:
        logger.info("Ardour connection test successful")
    else:
        logger.warning("Ardour ping failed (might be normal if Ardour doesn't respond)")

    client.disconnect()
    return success

def demonstrate_ardour_workflow():
    """Demonstrate complete Ardour workflow."""
    import tempfile
    import numpy as np
    import soundfile as sf

    logger.info("Demonstrating Ardour integration workflow...")

    # Create Ardour client
    ardour = ArdourClient()

    if not ardour.connect():
        logger.error("Cannot continue without Ardour connection")
        return False

    try:
        # 1. Create test audio file
        logger.info("1. Creating test audio file...")
        temp_dir = Path(tempfile.mkdtemp())
        test_audio = temp_dir / "test_tone.wav"

        # Generate 5-second test tone
        sample_rate = 44100
        duration = 5.0
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        tone = 0.3 * np.sin(2 * np.pi * 440 * t)  # 440 Hz sine wave

        sf.write(test_audio, tone, sample_rate)
        logger.info(f"Created test audio: {test_audio}")

        # 2. Create session (mock)
        logger.info("2. Setting up session...")
        ardour.create_session("AI_Music_Session", sample_rate=44100, tempo=120.0)

        # 3. Create tracks
        logger.info("3. Creating tracks...")
        tracks = ["AI_Lead", "AI_Pads", "AI_Drums", "AI_Bass"]
        for track in tracks:
            ardour.create_track(track, "audio", color="green")
            time.sleep(0.1)  # Small delay between commands

        # 4. Import audio to tracks
        logger.info("4. Importing audio to tracks...")
        for i, track in enumerate(tracks):
            position = i * 2.0  # Stagger positions
            ardour.import_audio(test_audio, track, position=position, gain=0.8)
            time.sleep(0.1)

        # 5. Add markers
        logger.info("5. Adding markers...")
        ardour.add_marker("Intro", 0.0, "blue")
        ardour.add_marker("Verse", 8.0, "green")
        ardour.add_marker("Chorus", 16.0, "yellow")
        ardour.add_marker("Outro", 24.0, "red")

        # 6. Control transport
        logger.info("6. Controlling transport...")
        ardour.set_transport("stop")
        time.sleep(0.5)
        ardour.set_transport("play")
        time.sleep(2.0)
        ardour.set_transport("stop")

        # 7. Cleanup
        logger.info("7. Cleaning up...")
        ardour.disconnect()

        # Clean up temp file
        test_audio.unlink()
        temp_dir.rmdir()

        logger.info("Ardour workflow demonstration completed successfully!")
        return True

    except Exception as e:
        logger.error(f"Error during Ardour workflow: {e}")
        ardour.disconnect()
        return False

def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Ardour DAW integration example"
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Ardour host address"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3819,
        help="Ardour OSC port"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test connection to Ardour"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run complete workflow demonstration"
    )
    parser.add_argument(
        "--import-audio",
        type=Path,
        help="Import audio file to Ardour"
    )
    parser.add_argument(
        "--track",
        default="AI_Track",
        help="Track name for audio import"
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

    logger.info("Ardour DAW Integration")
    logger.info("=" * 50)

    try:
        if args.test:
            # Test connection
            success = test_ardour_connection(args.host, args.port)
            sys.exit(0 if success else 1)

        elif args.demo:
            # Run demonstration
            success = demonstrate_ardour_workflow()
            sys.exit(0 if success else 1)

        elif args.import_audio:
            # Import specific audio file
            ardour = ArdourClient(args.host, args.port)
            if not ardour.connect():
                sys.exit(1)

            success = ardour.import_audio(args.import_audio, args.track)
            ardour.disconnect()
            sys.exit(0 if success else 1)

        else:
            # Show usage
            logger.info("No action specified. Available options:")
            logger.info("  --test          Test Ardour connection")
            logger.info("  --demo          Run complete workflow demonstration")
            logger.info("  --import-audio  Import specific audio file")
            logger.info("\nExample usage:")
            logger.info("  python ardour_integration.py --test")
            logger.info("  python ardour_integration.py --demo")
            logger.info("  python ardour_integration.py --import-audio song.wav --track Lead")

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()