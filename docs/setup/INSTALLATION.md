# Installation Guide

This guide covers the installation of AI music generation tools and dependencies for the project.

## Prerequisites

### System Requirements

- **Python**: 3.10 or higher
- **Memory**: 8GB RAM minimum, 16GB+ recommended
- **Storage**: 10GB+ free space for models
- **GPU**: Optional but recommended for faster generation (NVIDIA GPU with CUDA support)

### Required System Tools

- **Git**: For version control
- **FFmpeg**: For audio processing
  ```bash
  # macOS
  brew install ffmpeg
  
  # Ubuntu/Debian
  sudo apt-get install ffmpeg
  
  # Windows (via Chocolatey)
  choco install ffmpeg
  ```

- **SoX** (Optional): For audio manipulation
  ```bash
  # macOS
  brew install sox
  
  # Ubuntu/Debian
  sudo apt-get install sox
  ```

## Installation Methods

### Method 1: Complete Installation (Recommended)

Use the installation script for a complete setup:

```bash
# Make the script executable
chmod +x scripts/setup/install_ai_tools.py

# Run complete installation
python scripts/setup/install_ai_tools.py --tools all --download-models --verify
```

### Method 2: Step-by-Step Installation

#### 1. Set up Python Environment

**Using Conda (Recommended):**
```bash
conda create -n ai-music python=3.10
conda activate ai-music
```

**Using venv:**
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

#### 2. Install Core Dependencies

```bash
# Install project in development mode
pip install -e .

# Or with specific extras
pip install -e ".[dev,musicgen]"  # For development + MusicGen
```

#### 3. Install AI Music Tools

**AudioCraft (MusicGen):**
```bash
pip install audiocraft transformers accelerate
```

**Magenta (MIDI Generation):**
```bash
pip install magenta tensorflow
```

**Riffusion:**
```bash
pip install diffusers transformers torch torchaudio
```

**Stable Audio:**
```bash
pip install diffusers transformers scipy soundfile
```

#### 4. Install Audio Processing Tools

```bash
pip install librosa soundfile pydub mido pretty-midi pyrubberband python-osc
```

#### 5. Install Development Tools

```bash
pip install pytest pytest-cov black flake8 mypy sphinx sphinx-rtd-theme
```

### Method 3: Using the Setup Script

The project includes a comprehensive setup script:

```bash
# Basic setup
python scripts/setup/setup_project.py

# With specific options
python scripts/setup/setup_project.py --no-conda --python 3.11 --extras dev musicgen
```

## Model Downloads

### Automatic Download

Most models are downloaded automatically on first use via Hugging Face:

```python
from transformers import AutoModel, AutoProcessor

# MusicGen will download automatically
model = AutoModel.from_pretrained("facebook/musicgen-medium")
```

### Manual Download (Optional)

For offline use or faster first-time setup:

```bash
# Create models directory
mkdir -p data/models

# Download specific models (example)
python scripts/setup/download_models.py --model musicgen-medium --output-dir data/models
```

### Available Models

| Model | Identifier | Size | Notes |
|-------|------------|------|-------|
| **MusicGen Small** | `facebook/musicgen-small` | ~1.5GB | Fast, lower quality |
| **MusicGen Medium** | `facebook/musicgen-medium` | ~3GB | Good balance |
| **MusicGen Large** | `facebook/musicgen-large` | ~6GB | Highest quality |
| **MusicGen Melody** | `facebook/musicgen-melody` | ~3GB | Melody-conditional |
| **Riffusion** | `riffusion/riffusion-model-v1` | ~2GB | Audio generation |
| **Stable Audio** | `stabilityai/stable-audio-tools` | ~4GB | Text-to-audio |

## Environment Configuration

### 1. Copy Environment Template

```bash
cp .env.example .env
```

### 2. Edit `.env` File

Add your API keys and configuration:

```bash
# API Keys
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
HUGGINGFACE_TOKEN=your_key_here

# Audio Settings
SAMPLE_RATE=44100
BIT_DEPTH=24

# DAW Integration
ARDOUR_HOST=localhost
ARDOUR_PORT=3819
```

### 3. Environment Variables for GPU

**CUDA Setup (NVIDIA GPU):**
```bash
# Verify CUDA is available
python -c "import torch; print(torch.cuda.is_available())"

# Set CUDA device (if multiple GPUs)
export CUDA_VISIBLE_DEVICES=0
```

**MPS Setup (Apple Silicon):**
```bash
# For PyTorch on Apple Silicon
export PYTORCH_ENABLE_MPS_FALLBACK=1
```

## Verification

### Test Installation

Run the verification script:

```bash
python scripts/setup/install_ai_tools.py --verify
```

### Run Basic Tests

```bash
# Test project structure
pytest tests/unit/test_project_structure.py

# Test basic generation (mock)
python scripts/examples/basic_generation.py --prompt "test" --duration 5
```

### Test Specific Components

**Test MusicGen (if installed):**
```bash
python scripts/examples/musicgen_generation.py --prompt "test" --duration 5 --device cpu
```

**Test Audio Processing:**
```bash
# Create test audio first
python -c "import numpy as np; import soundfile as sf; sf.write('test.wav', np.random.randn(44100), 44100)"

# Process it
python scripts/examples/audio_processing.py --input test.wav
```

## Troubleshooting

### Common Issues

#### 1. CUDA/GPU Issues

**Error**: `CUDA not available`
```bash
# Check CUDA installation
nvidia-smi

# Reinstall PyTorch with CUDA
pip uninstall torch torchaudio
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
```

#### 2. Audio Library Issues

**Error**: `libsndfile not found`
```bash
# macOS
brew install libsndfile

# Ubuntu/Debian
sudo apt-get install libsndfile1
```

#### 3. Memory Issues

**Error**: `CUDA out of memory`
- Reduce batch size: `--batch-size 1`
- Use smaller model: `--model facebook/musicgen-small`
- Use CPU: `--device cpu`

#### 4. Model Download Issues

**Error**: `Connection error downloading model`
```bash
# Set Hugging Face token
export HUGGINGFACE_TOKEN=your_token

# Or use offline mode
export TRANSFORMERS_OFFLINE=1
export DIFFUSERS_OFFLINE=1
```

### Getting Help

1. Check the [Troubleshooting Guide](troubleshooting/README.md)
2. Search existing issues on GitHub
3. Create a new issue with:
   - Error message
   - Python version
   - Installed packages (`pip list`)
   - System information

## Updating

### Update Dependencies

```bash
# Update all packages
pip install --upgrade -r requirements.txt

# Update specific tool
pip install --upgrade audiocraft

# Update project
pip install -e . --upgrade
```

### Update Models

Most models update automatically. To clear cache and redownload:

```bash
# Clear Hugging Face cache
rm -rf ~/.cache/huggingface

# Or specific model
python -c "from transformers import AutoModel; AutoModel.from_pretrained('facebook/musicgen-medium', force_download=True)"
```

## Next Steps

After successful installation:

1. **Explore Examples**: Run the example scripts in `scripts/examples/`
2. **Try Notebooks**: Open Jupyter notebooks in `notebooks/`
3. **Read Documentation**: Check `docs/` for detailed guides
4. **Start Developing**: Modify scripts or create your own in `src/`

## Support

For installation issues:

- Check the [FAQ](troubleshooting/FAQ.md)
- Open an issue on GitHub
- Ask in the community forum (if available)