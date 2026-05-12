//
//  AppSettings.swift
//  AiMusic
//
//  Observable singleton for the connection settings. Server URL +
//  preference for LAN-first live in UserDefaults; the auth token is
//  stored in the iOS Keychain via `Keychain.swift` and surfaced here
//  as a `@Published` mirror so SwiftUI views can bind to it.
//

import Foundation
import Combine

@MainActor
final class AppSettings: ObservableObject {
    static let shared = AppSettings()

    // Plain-text settings — URLs and toggles aren't secrets.
    @Published var lanURL: String {
        didSet { defaults.set(lanURL, forKey: Keys.lanURL) }
    }

    @Published var remoteURL: String {
        didSet { defaults.set(remoteURL, forKey: Keys.remoteURL) }
    }

    @Published var preferLAN: Bool {
        didSet { defaults.set(preferLAN, forKey: Keys.preferLAN) }
    }

    // Mirror of the keychain-stored auth token. Writing this property
    // updates the keychain; reading returns the cached value.
    @Published var authToken: String {
        didSet {
            if authToken.isEmpty {
                Keychain.delete(account: Keys.authToken)
            } else {
                Keychain.set(authToken, account: Keys.authToken)
            }
        }
    }

    private let defaults = UserDefaults.standard

    private init() {
        self.lanURL = defaults.string(forKey: Keys.lanURL) ?? ""
        self.remoteURL = defaults.string(forKey: Keys.remoteURL) ?? ""
        self.preferLAN = defaults.object(forKey: Keys.preferLAN) as? Bool ?? true
        self.authToken = Keychain.get(account: Keys.authToken) ?? ""
    }

    /// Resolved URL to load in the WebView. Returns nil when nothing is
    /// configured. Honours `preferLAN`.
    var currentURL: URL? {
        let primary = preferLAN ? lanURL : remoteURL
        let fallback = preferLAN ? remoteURL : lanURL
        for candidate in [primary, fallback] {
            if let url = URL(string: candidate.trimmingCharacters(in: .whitespacesAndNewlines)),
               url.host != nil {
                return url
            }
        }
        return nil
    }

    var hasUsableURL: Bool { currentURL != nil }

    func clearAll() {
        lanURL = ""
        remoteURL = ""
        authToken = ""
    }

    private enum Keys {
        static let lanURL = "aiMusic.lanURL"
        static let remoteURL = "aiMusic.remoteURL"
        static let preferLAN = "aiMusic.preferLAN"
        static let authToken = "aiMusic.authToken"
    }
}
