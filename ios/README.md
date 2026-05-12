# AI Music — iOS app

A small SwiftUI wrapper around the AI Music Studio Gradio UI. The app
auto-discovers your Mac on Wi-Fi via mDNS / Bonjour, falls back to a
Tailscale URL when off-network, and hosts the full Studio in a
`WKWebView` (with the auth token injected as `X-AI-Music-Token` +
HTTP Basic Auth).

## Build

The `.xcodeproj` is generated from `project.yml` via [XcodeGen][xg],
so the repo only tracks the source files — no fragile `project.pbxproj`
diffs.

```sh
# one-time
brew install xcodegen

# generate (re-run any time project.yml changes)
cd ios
xcodegen

# open in Xcode
open AiMusic.xcodeproj
```

In Xcode:

1. Select the **AiMusic** target.
2. **Signing & Capabilities** → set your Apple ID as the development
   team. A free account is fine for personal sideloading.
3. Connect your iPhone via cable, pick it as the run destination,
   and hit Run. Trust the developer cert from
   *Settings → General → VPN & Device Management* on the phone.

## First launch

On first launch the app shows a **Connection** screen:

- *Discovered on Wi-Fi* lists Bonjour services with type
  `_ai-music._tcp` — your Mac running the Studio appears within a
  second or two when both devices are on the same network.
- *Manual / remote URL* takes a paste of your Tailscale Mac hostname
  (e.g. `http://my-mac:7860`) for off-LAN access.
- *Auth token* is optional. If you set `AI_MUSIC_AUTH_TOKEN` on the
  server, paste the same value here. It's stored in the iOS Keychain.

Tap **Test connection** to verify `/healthz` responds; **Save and
connect** loads the Studio in the WebView.

## Layout

```
ios/
├── project.yml                       # XcodeGen spec → AiMusic.xcodeproj
├── AiMusic/
│   ├── AiMusicApp.swift              # @main + RootView
│   ├── Info.plist                    # NSBonjourServices, ATS exceptions
│   ├── Assets.xcassets/              # AppIcon (placeholder), AccentColor
│   ├── Networking/
│   │   ├── NetworkManager.swift      # URLSession + auth header injection
│   │   ├── DiscoveryManager.swift    # NWBrowser for _ai-music._tcp
│   │   └── HealthCheck.swift         # GET /healthz with parsed reply
│   ├── Storage/
│   │   ├── AppSettings.swift         # ObservableObject — URLs + token
│   │   └── Keychain.swift            # SecItem wrapper for the token
│   └── Views/
│       ├── ConnectionView.swift      # first-launch picker
│       ├── MainView.swift            # WKWebView host
│       └── SettingsView.swift        # modal — edit URL/token/prefs
└── README.md                         # you are here
```

## Why a hybrid (WebView now, native later)?

The full Studio UI is built with Gradio — re-implementing every tab in
SwiftUI would be months of work and brittle to drift as the server
side evolves. The WebView wrapper gives you the entire app on day one;
the SwiftUI scaffold (NavigationStack, NetworkManager, AppSettings) is
deliberately structured so individual tabs can be re-skinned natively
later by replacing `MainView` with a `TabView` that hands certain tabs
to `StudioWebView` and others to native SwiftUI screens — talking to
the same `/api/predict` endpoint Gradio already exposes.

[xg]: https://github.com/yonaskolb/XcodeGen
