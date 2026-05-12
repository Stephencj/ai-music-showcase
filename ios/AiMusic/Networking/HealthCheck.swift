//
//  HealthCheck.swift
//  AiMusic
//
//  GET <baseURL>/healthz with a short timeout, returning the parsed
//  JSON shape from the FastAPI route (status / service / version /
//  host). Used by the Connection screen's "Test connection" button
//  and by the auto-connect flow on launch.
//

import Foundation

struct HealthResponse: Codable, Equatable {
    let status: String
    let service: String
    let version: String
    let host: String

    var isOK: Bool { status == "ok" && service == "ai-music-studio" }
}

enum HealthCheckError: LocalizedError {
    case invalidURL
    case unauthorized
    case unreachable(String)
    case badResponse(Int)
    case malformed

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "Not a valid URL."
        case .unauthorized: return "Auth token rejected by the server."
        case .unreachable(let reason): return "Couldn't reach the server: \(reason)."
        case .badResponse(let code): return "Server replied with HTTP \(code)."
        case .malformed: return "Server reply didn't look like AI Music Studio."
        }
    }
}

enum HealthCheck {
    /// Probe `<baseURL>/healthz`. Returns the parsed reply on success.
    static func probe(baseURL: String, token: String, timeout: TimeInterval = 3) async -> Result<HealthResponse, HealthCheckError> {
        guard var components = URLComponents(string: baseURL) else {
            return .failure(.invalidURL)
        }
        // Allow the user to paste either "http://host:port" or just
        // "host:port" — normalize the scheme.
        if components.scheme == nil { components.scheme = "http" }
        components.path = "/healthz"
        guard let url = components.url else { return .failure(.invalidURL) }

        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = "GET"
        request = NetworkManager.shared.authorized(request, token: token)

        do {
            let (data, response) = try await NetworkManager.shared.session.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return .failure(.malformed)
            }
            switch http.statusCode {
            case 200:
                if let parsed = try? JSONDecoder().decode(HealthResponse.self, from: data),
                   parsed.isOK {
                    return .success(parsed)
                }
                return .failure(.malformed)
            case 401, 403:
                return .failure(.unauthorized)
            default:
                return .failure(.badResponse(http.statusCode))
            }
        } catch {
            return .failure(.unreachable(error.localizedDescription))
        }
    }
}
