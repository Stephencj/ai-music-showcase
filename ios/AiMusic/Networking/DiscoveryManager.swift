//
//  DiscoveryManager.swift
//  AiMusic
//
//  mDNS / Bonjour browser for `_ai-music._tcp.local` services. The Mac
//  running the Studio advertises itself via zeroconf (see
//  `src/serve/discovery.py` on the server side); this resolves those
//  advertisements into `DiscoveredService` rows for the ConnectionView
//  picker.
//
//  Uses Network.framework's `NWBrowser` — the modern replacement for
//  `NSNetServiceBrowser`. Requires the `NSBonjourServices` and
//  `NSLocalNetworkUsageDescription` keys in Info.plist.
//

import Foundation
import Network
import Combine

struct DiscoveredService: Identifiable, Hashable {
    let id: String           // stable identity = host:port
    let name: String         // user-friendly instance name
    let host: String         // either "<name>.local" or a literal IP
    let port: Int
    let version: String?     // from TXT record

    var url: String { "http://\(host):\(port)" }
}

@MainActor
final class DiscoveryManager: ObservableObject {
    @Published private(set) var services: [DiscoveredService] = []
    @Published private(set) var isBrowsing = false
    @Published private(set) var lastError: String?

    private var browser: NWBrowser?

    /// Start browsing. Idempotent — safe to call from `.onAppear`.
    func start() {
        guard browser == nil else { return }

        let params = NWParameters()
        params.includePeerToPeer = false

        let descriptor = NWBrowser.Descriptor.bonjourWithTXTRecord(
            type: "_ai-music._tcp", domain: "local."
        )
        let browser = NWBrowser(for: descriptor, using: params)

        browser.stateUpdateHandler = { [weak self] state in
            Task { @MainActor in
                guard let self = self else { return }
                switch state {
                case .ready:
                    self.isBrowsing = true
                    self.lastError = nil
                case .failed(let error):
                    self.isBrowsing = false
                    self.lastError = error.localizedDescription
                case .cancelled:
                    self.isBrowsing = false
                default:
                    break
                }
            }
        }

        browser.browseResultsChangedHandler = { [weak self] results, _ in
            Task { @MainActor in
                self?.handle(results: results)
            }
        }

        browser.start(queue: .main)
        self.browser = browser
    }

    func stop() {
        browser?.cancel()
        browser = nil
        isBrowsing = false
    }

    private func handle(results: Set<NWBrowser.Result>) {
        var resolved: [DiscoveredService] = []
        for result in results {
            guard case let .service(name, _, _, _) = result.endpoint else { continue }
            var version: String?
            if case let .bonjour(txt) = result.metadata {
                version = txt.dictionary["version"]
            }
            // We can't get a usable host:port directly from a `.service`
            // endpoint without resolving it through a connection. As a
            // pragmatic fallback, use the Bonjour name as the hostname
            // (resolves on the LAN as `<name>.local`).
            let safe = name.replacingOccurrences(of: " ", with: "-")
            resolved.append(DiscoveredService(
                id: name,
                name: name,
                host: "\(safe).local",
                port: 7860,
                version: version
            ))
        }
        // De-dup + alphabetical for stable list ordering
        var seen = Set<String>()
        services = resolved
            .filter { seen.insert($0.id).inserted }
            .sorted { $0.name < $1.name }
    }
}
