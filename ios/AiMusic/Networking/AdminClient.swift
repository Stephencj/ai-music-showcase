//
//  AdminClient.swift
//  AiMusic
//
//  Server-control client. Today it has one entrypoint —
//  POST /admin/restart — used by the Settings screen's "Restart Studio
//  Server" button. Mirrors the HealthCheck shape (Result-typed return,
//  same auth header injection via NetworkManager).
//
//  The /admin/restart endpoint always requires the auth token, so an
//  empty token is a UX-side guard: don't show the button when the
//  user hasn't configured one. AdminError.tokenRequired surfaces the
//  "you need a token first" message if they tap anyway.
//

import Foundation

enum AdminError: LocalizedError {
    case tokenRequired
    case invalidURL
    case unauthorized
    case forbidden(String)
    case unreachable(String)
    case badResponse(Int)

    var errorDescription: String? {
        switch self {
        case .tokenRequired:
            return "Set an auth token in Settings before using server control."
        case .invalidURL:
            return "Not a valid URL."
        case .unauthorized:
            return "Auth token rejected by the server."
        case .forbidden(let detail):
            return detail
        case .unreachable(let reason):
            return "Couldn't reach the server: \(reason)."
        case .badResponse(let code):
            return "Server replied with HTTP \(code)."
        }
    }
}

enum AdminClient {
    /// POST `<baseURL>/admin/restart`. Returns success on HTTP 202.
    static func restart(baseURL: String, token: String, timeout: TimeInterval = 5)
        async -> Result<Void, AdminError>
    {
        guard !token.isEmpty else { return .failure(.tokenRequired) }
        guard var components = URLComponents(string: baseURL) else {
            return .failure(.invalidURL)
        }
        if components.scheme == nil { components.scheme = "http" }
        components.path = "/admin/restart"
        guard let url = components.url else { return .failure(.invalidURL) }

        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = "POST"
        request = NetworkManager.shared.authorized(request, token: token)

        do {
            let (data, response) = try await NetworkManager.shared.session.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return .failure(.badResponse(0))
            }
            switch http.statusCode {
            case 202:
                return .success(())
            case 401:
                return .failure(.unauthorized)
            case 403:
                let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
                return .failure(.forbidden(detail ?? "Forbidden."))
            default:
                return .failure(.badResponse(http.statusCode))
            }
        } catch {
            return .failure(.unreachable(error.localizedDescription))
        }
    }

    /// Poll `/healthz` repeatedly until the server comes back up or
    /// the deadline passes. Used after a restart to give the user a
    /// "Server back online" confirmation without making them manually
    /// reload.
    static func waitForRecovery(baseURL: String, token: String,
                                deadline: TimeInterval = 10) async -> Bool {
        let start = Date()
        let interval: UInt64 = 500_000_000  // 0.5s
        while Date().timeIntervalSince(start) < deadline {
            let probe = await HealthCheck.probe(baseURL: baseURL, token: token, timeout: 1)
            if case .success = probe { return true }
            try? await Task.sleep(nanoseconds: interval)
        }
        return false
    }
}
