//
//  AiMusicApp.swift
//  AiMusic
//
//  Entry point. Owns the AppSettings singleton (server URL + auth token
//  in Keychain) and decides between the ConnectionView (first launch /
//  unconfigured) and MainView (configured + reachable).
//

import SwiftUI

@main
struct AiMusicApp: App {
    @StateObject private var settings = AppSettings.shared

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(settings)
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var settings: AppSettings

    var body: some View {
        if settings.hasUsableURL {
            MainView()
        } else {
            ConnectionView()
        }
    }
}
