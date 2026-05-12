# AI Music Studio — portable container
#
# Multi-stage build keeps the runtime image small. Python 3.12 (not 3.14)
# because the heavy native wheels (torch, pedalboard, soundfile) ship
# slow on 3.14 still. Apple Silicon hosts can't pass Metal/MPS through
# Docker, so MusicGen falls back to CPU when run inside the container
# (slow but functional — see README). MIDI compose / Studio / FluidSynth
# rendering run at full speed.

FROM python:3.12-slim AS builder

ARG INSTALL_EXTRAS=base
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build-time system deps. Kept in the builder stage so the runtime
# stage stays small.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml requirements.txt ./
COPY README.md ./

# Editable install copies just metadata; the source is mounted later.
RUN pip install --upgrade pip wheel setuptools \
    && pip install -r requirements.txt \
    && pip install "gradio>=6.0" "zeroconf>=0.130" "fastapi" "uvicorn[standard]"

# Opt-in heavyweight extras (MusicGen weights are ~300MB-3GB; only
# install if explicitly requested via `docker build --build-arg
# INSTALL_EXTRAS=musicgen`).
RUN if [ "$INSTALL_EXTRAS" = "musicgen" ]; then \
        pip install transformers accelerate ; \
    fi


FROM python:3.12-slim AS runtime

# Runtime native deps:
#   fluidsynth      — pyfluidsynth binding wraps the system libfluidsynth
#   libsndfile1     — soundfile/librosa
#   ffmpeg          — librosa/pydub for non-WAV codecs
#   curl            — Dockerfile HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
        fluidsynth \
        libsndfile1 \
        ffmpeg \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the prebuilt site-packages from the builder.
COPY --from=builder /usr/local/lib/python3.12/site-packages \
                    /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn

WORKDIR /app
COPY app.py ./
COPY src ./src
COPY data/soundfonts ./data/soundfonts
# Other data dirs (blocks / outputs / song_specs / logs) are mounted by
# docker compose so user content survives container rebuilds.

ENV AI_MUSIC_HOST=0.0.0.0 \
    AI_MUSIC_PORT=7860 \
    AI_MUSIC_SOUNDFONT=/app/data/soundfonts/MuseScore_General.sf3 \
    PYTHONUNBUFFERED=1

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${AI_MUSIC_PORT}/healthz \
        $( [ -n "$AI_MUSIC_AUTH_TOKEN" ] && \
           echo "-H X-AI-Music-Token:${AI_MUSIC_AUTH_TOKEN}" ) \
        > /dev/null || exit 1

CMD ["python", "app.py"]
