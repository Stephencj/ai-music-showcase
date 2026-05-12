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
            var hostnameTXT: String?
            if case let .bonjour(txt) = result.metadata {
                version = txt.dictionary["version"]
                hostnameTXT = txt.dictionary["hostname"]
            }
            // The mDNS-resolvable hostname is the Mac's short name +
            // ".local" — NOT the Bonjour service instance name (which
            // can contain spaces and doesn't resolve via the OS DNS
            // resolver). The server publishes the actual hostname in
            // a TXT record specifically so we can construct a working
            // URL here.
            let host: String
            if let hostnameTXT, !hostnameTXT.isEmpty {
                // Strip a trailing ".local" if present, then re-append
                // so callers always get the FQDN.
                let bare = hostnameTXT.hasSuffix(".local")
                    ? String(hostnameTXT.dropLast(".local".count))
                    : hostnameTXT
                host = "\(bare).local"
            } else {
                // No TXT hostname — fall back to the instance name,
                // sanitized. Works on small Bonjour-friendly names,
                // breaks on names with spaces.
                host = "\(name.replacingOccurrences(of: " ", with: "-")).local"
            }
            resolved.append(DiscoveredService(
                id: name,
                name: name,
                host: host,
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
