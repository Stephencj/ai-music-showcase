//
//  MainView.swift
//  AiMusic
//
//  Hosts the WKWebView pointed at the Studio's Gradio UI. Single-tab
//  for v1 — the SwiftUI scaffold is set up so native rewrites of
//  individual tabs can drop in later without touching this file.
//

import SwiftUI
import WebKit

struct MainView: View {
    @EnvironmentObject private var settings: AppSettings
    @State private var showSettings = false
    @State private var reloadToken = UUID()
    @State private var probeState: ProbeState = .idle
    @State private var probedHealth: HealthResponse?

    /// Result of probing the configured candidate URLs. Holds the
    /// resolved-working URL on success, or all attempted URLs + the
    /// error each one returned on failure.
    enum ProbeState: Equatable {
        case idle
        case probing(currentlyTrying: String)
        case ok(URL)
        case failed(attempts: [(url: String, error: String)])

        static func == (lhs: ProbeState, rhs: ProbeState) -> Bool {
            switch (lhs, rhs) {
            case (.idle, .idle): return true
            case (.probing(let a), .probing(let b)): return a == b
            case (.ok(let a), .ok(let b)): return a == b
            case (.failed(let a), .failed(let b)):
                return a.map { $0.url + $0.error } == b.map { $0.url + $0.error }
            default: return false
            }
        }
    }

    /// Probe-key identity used by `.task(id:)` — re-run when the user
    /// changes either URL or the prefer-LAN toggle in Settings.
    private var probeKey: String {
        [settings.lanURL, settings.remoteURL,
         settings.preferLAN ? "LAN" : "REMOTE"].joined(separator: "|")
    }

    /// Candidate URLs in the order we should probe them. Prefer-LAN
    /// puts LAN first then Remote; the inverse otherwise. Blank /
    /// malformed entries are dropped.
    private func candidates() -> [URL] {
        let urls: [String] = settings.preferLAN
            ? [settings.lanURL, settings.remoteURL]
            : [settings.remoteURL, settings.lanURL]
        return urls.compactMap { raw in
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty,
                  let url = URL(string: trimmed),
                  url.host != nil else { return nil }
            return url
        }
    }

    var body: some View {
        NavigationStack {
            Group {
                if candidates().isEmpty {
                    ContentUnavailableView {
                        Label("No server configured", systemImage: "wifi.exclamationmark")
                    } description: {
                        Text("Open Settings to connect to your Mac.")
                    } actions: {
                        Button("Settings") { showSettings = true }
                    }
                } else {
                    switch probeState {
                    case .idle:
                        ProgressView()
                    case .probing(let trying):
                        VStack(spacing: 12) {
                            ProgressView()
                            Text("Connecting to \(URL(string: trying)?.host ?? trying)…")
                                .foregroundStyle(.secondary)
                        }
                    case .failed(let attempts):
                        ContentUnavailableView {
                            Label("Can't reach the server", systemImage: "wifi.exclamationmark")
                        } description: {
                            VStack(spacing: 6) {
                                ForEach(attempts.indices, id: \.self) { idx in
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(attempts[idx].url)
                                            .font(.caption.monospaced())
                                            .foregroundStyle(.primary)
                                        Text(attempts[idx].error)
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                            }
                        } actions: {
                            Button("Retry") { Task { await probeAll() } }
                            Button("Settings") { showSettings = true }
                        }
                    case .ok(let url):
                        StudioWebView(url: settings.entryURL(base: url),
                                      token: settings.authToken, reloadToken: reloadToken)
                            .ignoresSafeArea(edges: .bottom)
                    }
                }
            }
            .navigationTitle("Music Producer")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        Task { await probeAll() }
                        reloadToken = UUID()
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showSettings = true
                    } label: {
                        Image(systemName: "gear")
                    }
                }
            }
            .sheet(isPresented: $showSettings, onDismiss: {
                Task { await probeAll() }
            }) {
                SettingsView()
            }
            .task(id: probeKey) {
                // Re-probe whenever URLs or LAN-preference change.
                // Skip when we already have a winning URL.
                if case .ok = probeState { return }
                await probeAll()
            }
        }
    }

    /// Walk candidate URLs in order. Use a short timeout on the
    /// first attempt (LAN should be ~50ms) so an unreachable LAN URL
    /// off-Wi-Fi fails fast and we move to Remote/Tailscale.
    private func probeAll() async {
        let urls = candidates()
        guard !urls.isEmpty else { return }
        var failures: [(url: String, error: String)] = []
        for (idx, url) in urls.enumerated() {
            let timeout: TimeInterval = idx == 0 ? 2 : 5
            probeState = .probing(currentlyTrying: url.absoluteString)
            let result = await HealthCheck.probe(
                baseURL: url.absoluteString,
                token: settings.authToken,
                timeout: timeout,
            )
            switch result {
            case .success(let health):
                probedHealth = health
                probeState = .ok(url)
                return
            case .failure(let err):
                failures.append((url.absoluteString, err.localizedDescription))
            }
        }
        probeState = .failed(attempts: failures)
    }
}

/// Bridges WKWebView into SwiftUI. The token is injected on every
/// navigation via `decidePolicyFor`, plus the initial load.
struct StudioWebView: UIViewRepresentable {
    let url: URL
    let token: String
    let reloadToken: UUID

    func makeCoordinator() -> Coordinator { Coordinator(token: token) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        // iOS 16.4+ exposes the JS `Element.requestFullscreen()` API
        // through WKPreferences. The Playback tab uses this to go
        // full-bleed; without the flag the request silently fails.
        if #available(iOS 16.4, *) {
            config.preferences.isElementFullscreenEnabled = true
        }
        // Send a mobile content mode so Gradio's responsive CSS picks
        // the phone layout instead of trying to squeeze the desktop
        // grid into 390pt of width.
        let pagePrefs = WKWebpagePreferences()
        pagePrefs.preferredContentMode = .mobile
        config.defaultWebpagePreferences = pagePrefs
        // Force a sane mobile viewport before the page's own CSS
        // touches it — without this Gradio sometimes renders at
        // 1024pt logical width and the user sees micro-text.
        let viewport = WKUserScript(
            source: """
            var m = document.createElement('meta');
            m.name = 'viewport';
            m.content = 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no';
            document.head.appendChild(m);
            """,
            injectionTime: .atDocumentEnd,
            forMainFrameOnly: true
        )
        config.userContentController.addUserScript(viewport)

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.scrollView.refreshControl = makeRefreshControl(webView: webView,
                                                               coordinator: context.coordinator)
        load(webView: webView)
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        // reloadToken changes when the user taps the reload toolbar
        // button. Force a fresh load with the current token.
        if context.coordinator.lastLoadedToken != reloadToken {
            context.coordinator.lastLoadedToken = reloadToken
            context.coordinator.token = token
            load(webView: webView)
        }
    }

    private func load(webView: WKWebView) {
        var request = URLRequest(url: url)
        request = NetworkManager.shared.authorized(request, token: token)
        webView.load(request)
    }

    private func makeRefreshControl(webView: WKWebView, coordinator: Coordinator) -> UIRefreshControl {
        let rc = UIRefreshControl()
        coordinator.refreshControl = rc
        rc.addAction(UIAction { [weak webView] _ in
            webView?.reload()
        }, for: .valueChanged)
        return rc
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        var token: String
        var lastLoadedToken: UUID = UUID()
        weak var refreshControl: UIRefreshControl?

        init(token: String) { self.token = token }

        func webView(_ webView: WKWebView,
                     decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            decisionHandler(.allow)
        }

        // File-download interception: Gradio surfaces "Download MIDI"
        // / "Download mix" by linking to URLs ending in .mid / .wav /
        // .mp3 / .zip etc. (or by returning a Content-Disposition:
        // attachment header). WKWebView's default behaviour is to
        // navigate AWAY from the Studio UI and try to render the file
        // inline — which wipes the user's work mid-session. We
        // intercept here, cancel that navigation, pull the file down
        // ourselves, then surface an iOS share sheet so the user can
        // pop it into Files / Music / AirDrop.
        func webView(_ webView: WKWebView,
                     decidePolicyFor navigationResponse: WKNavigationResponse,
                     decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
            guard let http = navigationResponse.response as? HTTPURLResponse,
                  let url = http.url else {
                decisionHandler(.allow)
                return
            }
            let disposition = (http.allHeaderFields["Content-Disposition"] as? String)
                ?? (http.allHeaderFields["content-disposition"] as? String)
                ?? ""
            let isAttachment = disposition.lowercased().contains("attachment")
            let downloadable = Coordinator.downloadableExtensions
            let urlExt = url.pathExtension.lowercased()
            let extLooksLikeDownload = downloadable.contains(urlExt)

            // Some Gradio downloads are MIME-typed but lack the
            // Content-Disposition header. Fall back to the extension
            // check so we still catch them.
            guard isAttachment || extLooksLikeDownload else {
                decisionHandler(.allow)
                return
            }

            decisionHandler(.cancel)
            self.downloadAndShare(
                from: url,
                suggestedFilename: Coordinator.filename(
                    from: disposition, fallback: url.lastPathComponent,
                ),
            )
        }

        static let downloadableExtensions: Set<String> = [
            "mid", "midi", "wav", "mp3", "flac", "ogg", "aiff", "aif",
            "zip", "pdf",
        ]

        static func filename(from disposition: String, fallback: String) -> String {
            // Pull "filename=foo.mid" out of a Content-Disposition
            // header. Falls back to the URL's last path component when
            // the header is missing / malformed.
            if let range = disposition.range(
                of: "filename\\*?=\"?([^\";]+)",
                options: [.regularExpression, .caseInsensitive]
            ) {
                let raw = String(disposition[range])
                if let eq = raw.firstIndex(of: "=") {
                    let name = raw[raw.index(after: eq)...]
                        .trimmingCharacters(in: CharacterSet(charactersIn: "\""))
                    if !name.isEmpty { return String(name) }
                }
            }
            return fallback.isEmpty ? "download.bin" : fallback
        }

        private func downloadAndShare(from url: URL, suggestedFilename: String) {
            var request = URLRequest(url: url)
            request = NetworkManager.shared.authorized(request, token: token)
            let task = NetworkManager.shared.session.downloadTask(
                with: request
            ) { [weak self] tempURL, _, error in
                guard let tempURL = tempURL, error == nil else { return }
                // Move the file to a stable temp location with the
                // suggested filename so the share sheet shows a sensible
                // title and the recipient app picks the right extension.
                let dest = FileManager.default.temporaryDirectory
                    .appendingPathComponent(suggestedFilename)
                try? FileManager.default.removeItem(at: dest)
                do {
                    try FileManager.default.moveItem(at: tempURL, to: dest)
                } catch {
                    return
                }
                Task { @MainActor in self?.presentShareSheet(for: dest) }
            }
            task.resume()
        }

        @MainActor
        private func presentShareSheet(for fileURL: URL) {
            guard let presenter = Coordinator.topMostViewController() else { return }
            let av = UIActivityViewController(
                activityItems: [fileURL],
                applicationActivities: nil,
            )
            // iPad needs the popover anchor; harmless on iPhone.
            av.popoverPresentationController?.sourceView = presenter.view
            av.popoverPresentationController?.sourceRect = CGRect(
                x: presenter.view.bounds.midX,
                y: presenter.view.bounds.midY,
                width: 0, height: 0,
            )
            presenter.present(av, animated: true)
        }

        @MainActor
        static func topMostViewController() -> UIViewController? {
            guard let scene = UIApplication.shared.connectedScenes
                    .compactMap({ $0 as? UIWindowScene }).first,
                  var top = scene.windows.first(where: \.isKeyWindow)?
                                .rootViewController else {
                return nil
            }
            while let presented = top.presentedViewController { top = presented }
            return top
        }

        func webView(_ webView: WKWebView,
                     didReceive challenge: URLAuthenticationChallenge,
                     completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
            guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodHTTPBasic,
                  !token.isEmpty else {
                completionHandler(.performDefaultHandling, nil)
                return
            }
            let credential = URLCredential(user: "ios", password: token, persistence: .forSession)
            completionHandler(.useCredential, credential)
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            refreshControl?.endRefreshing()
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            refreshControl?.endRefreshing()
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            refreshControl?.endRefreshing()
        }
    }
}

#Preview {
    MainView().environmentObject(AppSettings.shared)
}
