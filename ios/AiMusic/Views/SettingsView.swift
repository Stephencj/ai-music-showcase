//
//  SettingsView.swift
//  AiMusic
//
//  Modal sheet from MainView. Lets the user edit the LAN/remote URLs,
//  rotate the auth token, toggle LAN preference, and clear everything
//  to return to the first-launch flow.
//

import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.dismiss) private var dismiss
    @StateObject private var discovery = DiscoveryManager()

    @State private var probeResult: String?
    @State private var probeIsOK: Bool = false
    @State private var isProbing: Bool = false
    @State private var showingClearConfirm = false

    var body: some View {
        NavigationStack {
            Form {
                Section("LAN URL (auto-discovered when available)") {
                    TextField("http://my-mac.local:7860", text: $settings.lanURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    if !discovery.services.isEmpty {
                        ForEach(discovery.services) { service in
                            Button {
                                settings.lanURL = service.url
                            } label: {
                                HStack {
                                    Image(systemName: "wifi")
                                    Text(service.url)
                                }
                            }
                        }
                    }
                }

                Section("Remote URL (Tailscale)") {
                    TextField("http://my-mac:7860", text: $settings.remoteURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    Text("Set up Tailscale on your Mac and iPhone, then paste the Mac's MagicDNS hostname here.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("Connection preference") {
                    Toggle("Prefer LAN when available", isOn: $settings.preferLAN)
                }

                Section("Auth token") {
                    SecureField("AI_MUSIC_AUTH_TOKEN", text: $settings.authToken)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Text("Stored in iOS Keychain; sent as X-AI-Music-Token + HTTP Basic Auth.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section {
                    Button {
                        Task { await probe() }
                    } label: {
                        HStack {
                            if isProbing { ProgressView().controlSize(.small) }
                            Text("Test current connection")
                        }
                    }
                    .disabled(!settings.hasUsableURL || isProbing)

                    if let probeResult {
                        HStack {
                            Image(systemName: probeIsOK ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                                .foregroundStyle(probeIsOK ? .green : .red)
                            Text(probeResult).font(.callout)
                        }
                    }
                }

                Section {
                    Button("Clear all and reconnect…", role: .destructive) {
                        showingClearConfirm = true
                    }
                    .confirmationDialog("Clear all settings?",
                                       isPresented: $showingClearConfirm,
                                       titleVisibility: .visible) {
                        Button("Clear", role: .destructive) {
                            settings.clearAll()
                            dismiss()
                        }
                    } message: {
                        Text("Removes saved URLs and auth token. The app will return to the connection screen.")
                    }
                }
            }
            .navigationTitle("Settings")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .onAppear { discovery.start() }
            .onDisappear { discovery.stop() }
        }
    }

    private func probe() async {
        guard let url = settings.currentURL else { return }
        isProbing = true
        defer { isProbing = false }
        let result = await HealthCheck.probe(baseURL: url.absoluteString,
                                              token: settings.authToken)
        switch result {
        case .success(let health):
            probeIsOK = true
            probeResult = "Connected to \(health.host) — v\(health.version)"
        case .failure(let err):
            probeIsOK = false
            probeResult = err.localizedDescription
        }
    }
}

#Preview {
    SettingsView().environmentObject(AppSettings.shared)
}
