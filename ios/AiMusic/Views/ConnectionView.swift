//
//  ConnectionView.swift
//  AiMusic
//
//  First-launch + Settings screen. Browses for Studio servers on the
//  LAN via mDNS, lets the user type a manual URL (Tailscale/remote)
//  and an optional auth token, and verifies reachability via /healthz
//  before saving.
//

import SwiftUI

struct ConnectionView: View {
    @EnvironmentObject private var settings: AppSettings
    @StateObject private var discovery = DiscoveryManager()

    @State private var manualURL: String = ""
    @State private var tokenField: String = ""
    @State private var probeResult: String?
    @State private var probeIsOK: Bool = false
    @State private var isProbing: Bool = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Discovered on Wi-Fi") {
                    if discovery.services.isEmpty {
                        HStack {
                            ProgressView()
                            Text(discovery.isBrowsing
                                 ? "Looking for AI Music Studio on your network…"
                                 : "Not browsing")
                                .foregroundStyle(.secondary)
                        }
                    } else {
                        ForEach(discovery.services) { service in
                            Button {
                                manualURL = service.url
                                settings.lanURL = service.url
                                Task { await probe() }
                            } label: {
                                HStack {
                                    Image(systemName: "wifi")
                                    VStack(alignment: .leading) {
                                        Text(service.name).font(.headline)
                                        Text(service.url)
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                            }
                        }
                    }
                }

                Section("Manual / remote URL") {
                    TextField("http://my-mac:7860", text: $manualURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    Toggle("Prefer LAN when available", isOn: $settings.preferLAN)
                }

                Section("Auth token (optional)") {
                    SecureField("Leave empty if your server has no token",
                                text: $tokenField)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Text("Matches AI_MUSIC_AUTH_TOKEN on the server. Stored in iOS Keychain.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section {
                    Button {
                        Task { await probe() }
                    } label: {
                        HStack {
                            if isProbing {
                                ProgressView().controlSize(.small)
                            }
                            Text("Test connection")
                        }
                    }
                    .disabled(manualURL.trimmingCharacters(in: .whitespaces).isEmpty || isProbing)

                    if let probeResult {
                        HStack {
                            Image(systemName: probeIsOK ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                                .foregroundStyle(probeIsOK ? .green : .red)
                            Text(probeResult).font(.callout)
                        }
                    }
                }

                Section {
                    Button("Save and connect") { save() }
                        .frame(maxWidth: .infinity)
                        .disabled(!probeIsOK)
                }
            }
            .navigationTitle("AI Music Studio")
            .onAppear {
                manualURL = settings.remoteURL.isEmpty ? settings.lanURL : settings.remoteURL
                tokenField = settings.authToken
                discovery.start()
            }
            .onDisappear { discovery.stop() }
        }
    }

    private func probe() async {
        let target = manualURL.trimmingCharacters(in: .whitespaces)
        guard !target.isEmpty else { return }
        isProbing = true
        defer { isProbing = false }

        let result = await HealthCheck.probe(baseURL: target, token: tokenField)
        switch result {
        case .success(let health):
            probeIsOK = true
            probeResult = "Connected to \(health.host) — v\(health.version)"
        case .failure(let err):
            probeIsOK = false
            probeResult = err.localizedDescription
        }
    }

    private func save() {
        let trimmed = manualURL.trimmingCharacters(in: .whitespaces)
        // Heuristic: link-local addresses or *.local hostnames go in
        // the LAN slot; everything else in the remote slot.
        if trimmed.contains(".local") || trimmed.contains("192.168.") || trimmed.contains("10.") || trimmed.contains("172.") {
            settings.lanURL = trimmed
        } else {
            settings.remoteURL = trimmed
        }
        settings.authToken = tokenField
    }
}

#Preview {
    ConnectionView().environmentObject(AppSettings.shared)
}
