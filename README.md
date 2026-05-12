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

### Always-on (LaunchAgent)

If you want the server to start at login and respawn on crash so the
iPhone always finds it:

```bash
./scripts/setup/install_launch_agent.sh
```

The script absolutises paths, picks up `AI_MUSIC_AUTH_TOKEN` from
`.env` (prompts if missing), writes the plist to
`~/Library/LaunchAgents/com.stephencjuliano.aimusic.plist`, and
bootstraps it via `launchctl`. KeepAlive is on, so a crash or `kill
-9` triggers an automatic respawn within ~10s. Logs go to
`logs/launchd.out` and `logs/launchd.err`.

Verify:

```bash
launchctl list | grep aimusic   # shows the label + a numeric PID
curl http://127.0.0.1:7860/healthz
```

Uninstall: `./scripts/setup/uninstall_launch_agent.sh`.

The LaunchAgent runs as your user (not root), so it has access to your
venv, your data files, and your keychain. It only runs while you're
logged in — if the Mac reboots and you don't log back in, the server
stays down. For a headless Mac mini, set the Login Items so your
account logs in automatically at boot.

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
| `AI_MUSIC_AUTH_TOKEN` | _empty_ | Optional shared secret. When set, clients from outside `AI_MUSIC_TRUSTED_CIDRS` must send `X-AI-Music-Token` or HTTP Basic Auth (any username, this token as password). LAN clients bypass the check. |
| `AI_MUSIC_TRUSTED_CIDRS` | _LAN ranges_ | Comma-separated CIDRs that skip auth. Default: `127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`. Notably **excludes** Tailscale's `100.64.0.0/10` — tailnet peers always auth. |
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

Tailscale gives the Mac a stable private IP reachable from any device
on the same tailnet — no port forwarding, no public URL. The Studio
auth middleware specifically does NOT trust Tailscale's CGNAT range
(`100.64.0.0/10`), so requests from the tailnet require the token
even though LAN traffic on your home Wi-Fi skips it.

### 1. Install Tailscale on the Mac

Mac App Store (preferred — has the menu bar icon and updates
automatically) or:

```bash
brew install --cask tailscale
```

Open Tailscale, click *Sign in*, pick your auth provider
(Google / Apple / Microsoft / email). The menu bar icon turns blue
when connected. Click it to see the Mac's tailnet hostname (e.g.
`my-mac-mini`).

### 2. Install Tailscale on the iPhone

App Store → Tailscale → Sign in with the same account. Accept the VPN
profile when prompted (Tailscale runs as a VPN extension on iOS). In
the Tailscale iOS app, your Mac appears in the peer list once both
devices are signed in.

### 3. Set the auth token

The tailnet is private, but defence-in-depth costs nothing:

```bash
# In .env on the Mac
AI_MUSIC_AUTH_TOKEN=<long random string>
```

Re-run the LaunchAgent installer so the new token gets injected into
the plist:

```bash
./scripts/setup/install_launch_agent.sh
```

### 4. Configure the iOS app

In the AI Music app → Settings → **Remote URL**:
`http://my-mac-mini:7860` (short MagicDNS hostname). If
MagicDNS is disabled in your tailnet admin panel, use the full FQDN
shown in the Mac's Tailscale menu (`my-mac-mini.tailXXXX.ts.net`).

In the same Settings sheet → **Auth token**: paste the same string
from `.env`. Tap **Test current connection** — it should resolve to
the tailnet IP and reply with `ok`.

### 5. Test off Wi-Fi

Turn off Wi-Fi on the iPhone. The Studio still loads — slower than
LAN (each request crosses the Internet) but functional. The mDNS
discovery list will be empty off Wi-Fi (Bonjour is link-local only),
which is fine: the iOS app falls back to the saved Remote URL.

### Restarting the server remotely

Settings → **Restart Studio server** issues a `POST /admin/restart`
with the token. The server schedules a `SIGTERM`, uvicorn drains, and
the LaunchAgent's `KeepAlive` respawns it within a few seconds. The
iOS app polls `/healthz` and reports "Server back online" when it
recovers. Restart requires a token even from LAN (it's too dangerous
to let unauthenticated clients trigger).

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
