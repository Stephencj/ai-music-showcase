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

    var body: some View {
        NavigationStack {
            Group {
                if let url = settings.currentURL {
                    StudioWebView(url: url, token: settings.authToken, reloadToken: reloadToken)
                        .ignoresSafeArea(edges: .bottom)
                } else {
                    ContentUnavailableView(
                        "No server configured",
                        systemImage: "wifi.exclamationmark",
                        description: Text("Open Settings to connect to your Mac.")
                    )
                }
            }
            .navigationTitle("AI Music Studio")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
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
            .sheet(isPresented: $showSettings) {
                SettingsView()
            }
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
        rc.addAction(UIAction { [weak webView, weak rc] _ in
            webView?.reload()
            // The navigation delegate ends the refresh state when the
            // page finishes loading.
            _ = rc // silence unused-capture warning when nil
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
            // Append the auth header on outgoing top-level navigations
            // when not already present. Sub-resource requests (XHR /
            // WebSocket) inherit the cookie/credential from the initial
            // Basic Auth handshake; iOS's WKWebView surfaces 401 via
            // `didReceive challenge` below.
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
