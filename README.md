# AI Music Studio

A personal AI-powered music generation toolkit: Gradio web app for composing
MIDI (chords, bass, melody, drums), a bar-by-bar Melody Studio, a song-builder
that arranges blocks on a timeline, and audio rendering via FluidSynth +
SoundFont. Optional MusicGen integration generates audio from text prompts.

Includes an iOS wrapper app and a portable Docker image so you can run the
Studio from your iPhone — at home over Wi-Fi or anywhere via Tailscale.

## Architecture

```
  iPhone (ios/AiMusic)              Mac / Linux host
  ┌──────────────────────┐         ┌──────────────────────────────┐
  │ SwiftUI app          │         │ Gradio Blocks                │
  │ ├ WKWebView ─────────┼ HTTP ──┼─► FastAPI (gr.mount_gradio_app)│
  │ ├ NWBrowser (mDNS)   │         │   ├ /healthz                  │
  │ └ Keychain (token)   │         │   ├ TokenMiddleware           │
  └──────────────────────┘         │   └ Gradio UI + WebSockets    │
                                   │ + Zeroconf (_ai-music._tcp)   │
                                   └──────────────────────────────┘
```

The Mac advertises itself on the LAN; the iOS app discovers it via
Bonjour/mDNS and loads the Gradio UI in a WebView. Off-LAN access goes
through Tailscale (Mac and iPhone both on your tailnet).

## Quickstart — Mac native (recommended for daily use)

Native Python keeps MusicGen on Metal/MPS for full speed.

```bash
# clone, set up venv, install
git clone https://github.com/stephencjuliano/ai-music.git
cd ai-music
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# optional: copy + edit env (auth token, host, port)
cp .env.example .env

# launch — opens on http://0.0.0.0:7860 by default
./run.command
```

A startup banner prints the LAN URLs the iPhone can reach.

## Quickstart — Docker (portable / non-Mac hosts)

```bash
cp .env.example .env
# edit .env, especially AI_MUSIC_AUTH_TOKEN if exposing beyond LAN
docker compose up --build
```

On Apple Silicon Macs, Docker can't pass Metal/MPS through to the
container, so MusicGen falls back to CPU (5–10× slower). MIDI compose,
Studio, FluidSynth rendering, and the rest of the app run at full speed
either way. The native path is recommended on Mac; the container is for
Linux boxes, cloud VMs, or as a clean-room reproducer.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AI_MUSIC_HOST` | `0.0.0.0` | Bind address. `127.0.0.1` for localhost-only. |
| `AI_MUSIC_PORT` | `7860` | Port for the Gradio server. |
| `AI_MUSIC_AUTH_TOKEN` | _empty_ | Optional shared secret. Gates the UI with HTTP Basic Auth and `/healthz` with `X-AI-Music-Token` header. |
| `AI_MUSIC_SHARE` | `false` | When `true`, exposes a `gradio.live` public URL. Tailscale is the preferred remote-access option. |
| `AI_MUSIC_SOUNDFONT` | _auto_ | Override the SoundFont path. Defaults to `data/soundfonts/MuseScore_General.sf3`. |

See `.env.example` for the full list (HuggingFace tokens, MusicGen cache
dirs, audio settings, etc.).

## iOS app

The Xcode project lives under `ios/AiMusic.xcodeproj`. iOS 17+, iPhone +
iPad, SwiftUI.

```bash
open ios/AiMusic.xcodeproj
```

In Xcode, set the development team to your Apple ID (free account is
fine for personal sideloading), pick your iPhone as the target, and
hit Run. On first launch the app browses for `_ai-music._tcp.local`
services — the Mac running the Studio appears within a couple of
seconds when both devices are on the same Wi-Fi.

For off-LAN access, install Tailscale on both Mac and iPhone, then
paste the Mac's MagicDNS hostname (e.g. `http://my-mac:7860`) as
the remote URL in the iOS Settings.

## Remote access via Tailscale

1. Install Tailscale: <https://tailscale.com/download> (Mac app, iOS
   from the App Store). Sign in with the same account on both.
2. Note the Mac's MagicDNS name from the Tailscale menu bar (something
   like `my-mac.your-tailnet.ts.net`, or just `my-mac` if
   MagicDNS is enabled).
3. In the iOS app Settings, set the remote URL to
   `http://my-mac:7860` (or use the longer ts.net hostname).
4. Set `AI_MUSIC_AUTH_TOKEN` in `.env` on the Mac and the matching
   token in the iOS Settings. The Tailnet is already private, but the
   token adds defence-in-depth against accidentally enabling Funnel.

## Testing

```bash
.venv/bin/python -m unittest discover -s tests
```

Tests cover music-theory primitives, the Studio UI wiring, the launcher
+ auth middleware, and the block/song stores. Live UI testing happens
in a browser against `http://127.0.0.1:7860` or via the iOS app.

## Project layout

```
ai-music/
├── app.py                         # Gradio entry — the entire UI lives here
├── src/
│   ├── audio_processing/render/   # FluidSynth + mix pipeline
│   ├── daw_integration/generic/   # MIDI exporter, blocks, songs, melody plan
│   ├── models/                    # MusicGen + other audio-model wrappers
│   └── serve/                     # Launcher, auth, mDNS, /healthz
├── data/
│   ├── blocks/                    # Saved composition blocks (yaml + mid + wav)
│   ├── songs/                     # Saved song specs (timeline of blocks)
│   ├── song_specs/                # Curated example songs
│   └── soundfonts/                # MuseScore_General.sf3 (downloaded on demand)
├── ios/                           # SwiftUI wrapper app
├── tests/unit/                    # Test suite
├── Dockerfile                     # Portable container
└── compose.yaml                   # `docker compose up` to run
```

## License

Private use. See LICENSE if/when added.
