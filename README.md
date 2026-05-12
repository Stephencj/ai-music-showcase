# AI Music Generation Toolkit

A comprehensive toolkit for AI-powered music generation, processing, and DAW integration.

## Features

- **Multiple AI Model Support**: MusicGen, AudioCraft, Riffusion, Stable Audio, and custom models
- **Audio Processing Pipeline**: Preprocessing, postprocessing, effects, and analysis
- **DAW Integration**: Ardour, Reaper, and generic MIDI/OSC support
- **Flexible Workflow Orchestration**: Pipeline-based generation with automation
- **Extensible Architecture**: Plugin system for adding new models and processors
- **Comprehensive Testing**: Unit, integration, and audio quality tests
- **Documentation**: Setup guides, API reference, and workflow examples

## Project Structure

```
ai-music/
├── src/                    # Source code
│   ├── models/            # AI model implementations
│   ├── audio_processing/  # Audio processing utilities
│   ├── daw_integration/   # DAW integration modules
│   ├── api/               # API integrations
│   ├── workflow/          # Workflow orchestration
│   └── utils/             # Utility functions
├── config/                # Configuration files
├── data/                  # Data storage
├── tests/                 # Test suite
├── docs/                  # Documentation
├── scripts/               # Utility scripts
├── notebooks/             # Jupyter notebooks
└── logs/                  # Application logs
```

## Quick Start

### 1. Prerequisites

- Python 3.10 or higher
- Conda or venv for virtual environment management
- Git for version control
- Audio tools: FFmpeg, SoX (optional but recommended)

### 2. Installation

```bash
# Clone repository
git clone https://github.com/stephencjuliano/ai-music.git
cd ai-music

# Create and activate conda environment
conda create -n ai-music python=3.10
conda activate ai-music

# Or using venv
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install package in development mode
pip install -e ".[dev,musicgen]"  # Install with dev tools and MusicGen support

# Set up environment
cp .env.example .env
# Edit .env with your API keys and settings
```

### 3. Basic Usage

```python
from src.workflow.pipelines.basic_generation import BasicGenerationPipeline

# Initialize pipeline
pipeline = BasicGenerationPipeline()

# Generate music
output_path = pipeline.run(
    prompt="A relaxing ambient track with piano and strings",
    duration=60.0
)

print(f"Generated audio saved to: {output_path}")
```

### 4. Running Examples

```bash
# Run basic generation example
python scripts/examples/basic_generation.py

# Run with specific model
python scripts/examples/musicgen_generation.py --prompt "upbeat electronic dance music"

# Process existing audio
python scripts/examples/audio_processing.py --input audio.wav
```

## Model Support

### Currently Supported Models

| Model | Type | Requirements | Notes |
|-------|------|--------------|-------|
| **MusicGen** | Text-to-music | `pip install -e ".[musicgen]"` | Facebook's music generation model |
| **AudioCraft** | Text-to-music | `pip install audiocraft` | Meta's audio generation framework |
| **Riffusion** | Text-to-audio | `pip install -e ".[riffusion]"` | Stable Diffusion for audio |
| **Stable Audio** | Text-to-audio | `pip install diffusers` | Stability AI's audio model |
| **Custom Models** | Various | Custom installation | Support for custom model implementations |

### Adding New Models

1. Create model directory in `src/models/`
2. Implement base interface from `src/models/base.py`
3. Add configuration in `config/models/`
4. Register model in `src/models/__init__.py`

## DAW Integration

### Ardour Integration

```python
from src.daw_integration.ardour.client import ArdourClient

# Connect to Ardour
ardour = ArdourClient(host="localhost", port=3819)

# Create track and import audio
ardour.create_track("AI_Generated", "audio")
ardour.import_audio("generated.wav", "AI_Generated")
```

### Reaper Integration

```python
from src.daw_integration.reaper.client import ReaperClient

# Connect to Reaper
reaper = ReaperClient(host="localhost", port=8080)

# Send MIDI data
reaper.send_midi(note=60, velocity=100, duration=1.0)
```

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# API Keys
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here

# Audio Settings
SAMPLE_RATE=44100
BIT_DEPTH=24

# DAW Settings
ARDOUR_HOST=localhost
ARDOUR_PORT=3819
```

### Model Configuration

Model-specific settings in `config/models/`:

```yaml
# config/models/musicgen.yaml
model_size: "medium"
duration: 30.0
temperature: 1.0
top_p: 0.9
```

## Development

### Setting Up Development Environment

```bash
# Install development dependencies
pip install -e ".[dev]"

# Set up pre-commit hooks
pre-commit install

# Run tests
pytest

# Run with coverage
pytest --cov=src tests/

# Type checking
mypy src/

# Code formatting
black src/ tests/
```

### Testing

```bash
# Run all tests
pytest

# Run specific test category
pytest tests/unit/
pytest tests/integration/
pytest tests/audio/

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=src --cov-report=html
```

### Code Quality

- **Formatting**: Black (line length: 88)
- **Linting**: Flake8
- **Type Checking**: MyPy
- **Import Sorting**: isort (via pre-commit)

## Workflow Examples

### Basic Generation Pipeline

```python
from src.workflow.pipelines.basic_generation import BasicGenerationPipeline

pipeline = BasicGenerationPipeline()
output = pipeline.run("upbeat electronic music", duration=45.0)
```

### Batch Processing

```python
from src.workflow.automation.batch_processor import BatchProcessor

processor = BatchProcessor()
prompts = ["ambient drone", "jazz fusion", "techno beat"]
results = processor.process_batch(prompts, duration=30.0)
```

### DAW Automation

```python
from src.workflow.automation.daw_automation import DawAutomation

automation = DawAutomation()
automation.create_session("My AI Album", tracks=8)
automation.generate_and_import_tracks(prompts, durations=[60, 90, 120])
```

## Documentation

- [Setup Guide](docs/setup/README.md): Detailed installation and configuration
- [API Reference](docs/api/README.md): Complete API documentation
- [Workflow Examples](docs/workflows/README.md): Step-by-step workflow guides
- [Troubleshooting](docs/troubleshooting/README.md): Common issues and solutions
- [Contributing](CONTRIBUTING.md): How to contribute to the project

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Acknowledgments

- Facebook Research for MusicGen and AudioCraft
- Stability AI for Stable Audio
- Riffusion team for Riffusion
- Ardour and Reaper teams for DAW software
- All open-source audio libraries used in this project

## Support

- [GitHub Issues](https://github.com/stephencjuliano/ai-music/issues): Bug reports and feature requests
- [Documentation](docs/): Comprehensive guides and references
- [Examples](scripts/examples/): Ready-to-run example scripts