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

    enum ProbeState: Equatable {
        case idle
        case probing
        case ok
        case failed(String)
    }

    var body: some View {
        NavigationStack {
            Group {
                if let url = settings.currentURL {
                    switch probeState {
                    case .idle, .probing:
                        VStack(spacing: 12) {
                            ProgressView()
                            Text("Connecting to \(url.host ?? "server")…")
                                .foregroundStyle(.secondary)
                        }
                    case .failed(let msg):
                        ContentUnavailableView {
                            Label("Can't reach the server", systemImage: "wifi.exclamationmark")
                        } description: {
                            VStack(spacing: 6) {
                                Text(msg).multilineTextAlignment(.center)
                                Text(url.absoluteString).font(.caption).foregroundStyle(.secondary)
                            }
                        } actions: {
                            Button("Retry") { Task { await probe(url) } }
                            Button("Settings") { showSettings = true }
                        }
                    case .ok:
                        StudioWebView(url: url, token: settings.authToken, reloadToken: reloadToken)
                            .ignoresSafeArea(edges: .bottom)
                    }
                } else {
                    ContentUnavailableView {
                        Label("No server configured", systemImage: "wifi.exclamationmark")
                    } description: {
                        Text("Open Settings to connect to your Mac.")
                    } actions: {
                        Button("Settings") { showSettings = true }
                    }
                }
            }
            .navigationTitle("AI Music Studio")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        if let url = settings.currentURL {
                            Task { await probe(url) }
                        }
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
                if let url = settings.currentURL {
                    Task { await probe(url) }
                }
            }) {
                SettingsView()
            }
            .onChange(of: settings.currentURL) { _, newURL in
                if let newURL { Task { await probe(newURL) } }
            }
            .task(id: settings.currentURL?.absoluteString ?? "") {
                // Bound to the NavigationStack body, so it isn't
                // cancelled by inner view transitions (e.g. .idle →
                // .probing). The `id` triggers a re-run when the
                // resolved URL changes.
                if let url = settings.currentURL, probeState != .ok {
                    await probe(url)
                }
            }
        }
    }

    private func probe(_ url: URL) async {
        probeState = .probing
        let result = await HealthCheck.probe(baseURL: url.absoluteString,
                                              token: settings.authToken,
                                              timeout: 4)
        switch result {
        case .success(let health):
            probedHealth = health
            probeState = .ok
        case .failure(let err):
            probeState = .failed(err.localizedDescription)
        }
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
