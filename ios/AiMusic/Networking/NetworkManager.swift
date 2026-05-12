//
//  NetworkManager.swift
//  AiMusic
//
//  Shared URLSession + helper that injects the X-AI-Music-Token header
//  on outgoing requests. Used by HealthCheck and by the MainView's
//  WKWebView delegate to authorise navigation requests.
//

import Foundation

struct NetworkManager {
    static let shared = NetworkManager()

    let session: URLSession

    init() {
        let config = URLSessionConfiguration.default
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.timeoutIntervalForRequest = 10
        config.timeoutIntervalForResource = 30
        self.session = URLSession(configuration: config)
    }

    /// Wraps a `URLRequest` with the configured auth token, if any.
    func authorized(_ request: URLRequest, token: String) -> URLRequest {
        guard !token.isEmpty else { return request }
        var r = request
        r.setValue(token, forHTTPHeaderField: "X-AI-Music-Token")
        // Also set Basic Auth so the Gradio UI path is gated by the
        // same secret — Gradio's auth callable accepts any username.
        if let data = "ios:\(token)".data(using: .utf8) {
            let encoded = data.base64EncodedString()
            r.setValue("Basic \(encoded)", forHTTPHeaderField: "Authorization")
        }
        return r
    }
}
