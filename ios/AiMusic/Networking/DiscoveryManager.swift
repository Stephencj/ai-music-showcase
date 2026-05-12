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

/// Thread-safe once-flag for the NWConnection state-handler closure,
/// which Swift 6's strict concurrency won't let us mutate a captured
/// `var` from.
final class ResolvedFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var done = false
    /// Atomically set the flag. Returns `true` only the first time.
    func flip() -> Bool {
        lock.lock(); defer { lock.unlock() }
        if done { return false }
        done = true
        return true
    }
}


struct DiscoveredService: Identifiable, Hashable {
    let id: String           // stable identity = bonjour service name
    let name: String         // user-friendly instance name
    let host: String         // mDNS `.local` hostname
    let port: Int
    let version: String?     // from TXT record
    var resolvedIP: String?  // filled in async after discovery

    /// URL preferring the resolved IP — `.local` lookups go through
    /// Bonjour multicast on every request, which adds 100-500ms per
    /// fetch on a real iPhone. Once resolved, the WebView's API
    /// calls + WebSocket all hit the IP directly.
    var url: String {
        let h = resolvedIP ?? host
        let formatted = h.contains(":") && !h.hasPrefix("[") ? "[\(h)]" : h
        return "http://\(formatted):\(port)"
    }
}

@MainActor
final class DiscoveryManager: ObservableObject {
    @Published private(set) var services: [DiscoveredService] = []
    @Published private(set) var isBrowsing = false
    @Published private(set) var lastError: String?
    /// `true` once the first browse result lands, or browse fails — used
    /// by the UI to differentiate "still discovering" from "discovery
    /// finished, nothing here" (most likely Local Network permission
    /// was denied or the server isn't running).
    @Published private(set) var hasSettled = false

    private var browser: NWBrowser?
    private var primerConnection: NWConnection?
    private var settleTimer: Task<Void, Never>?
    /// Track which services we've already kicked off a resolve for —
    /// the browse callback fires repeatedly as TXT records update.
    private var resolvingIDs: Set<String> = []
    private var pendingResolvers: [NWConnection] = []

    /// Start browsing. Idempotent — safe to call from `.onAppear`.
    func start() {
        guard browser == nil else { return }

        // On a physical device, NWBrowser by itself doesn't trigger
        // the Local Network permission prompt — only an attempted
        // *connection* does. Without permission the browser silently
        // reports zero results, which used to read as "still looking"
        // in the UI. Open a tiny throwaway multicast connection to
        // 224.0.0.251:5353 (mDNS) so iOS surfaces the permission
        // alert. The connection is cancelled immediately after.
        primeLocalNetworkPermission()

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
                    self.hasSettled = true
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

        // "Settled" after a few seconds: either we found services or
        // we didn't. The UI uses this to stop showing the spinner.
        settleTimer?.cancel()
        settleTimer = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 3_500_000_000)
            await MainActor.run { self?.hasSettled = true }
        }
    }

    func stop() {
        browser?.cancel()
        browser = nil
        primerConnection?.cancel()
        primerConnection = nil
        settleTimer?.cancel()
        settleTimer = nil
        for conn in pendingResolvers { conn.cancel() }
        pendingResolvers.removeAll()
        resolvingIDs.removeAll()
        isBrowsing = false
    }

    /// Open a short-lived TCP probe to a discovered Bonjour service
    /// so we can read the underlying IP address from the resolved
    /// connection path. The IP gets cached on the DiscoveredService;
    /// the WebView uses it for all subsequent requests so Gradio's
    /// chatty queue isn't bottlenecked on per-request mDNS lookups.
    private func resolveToIP(serviceID: String, endpoint: NWEndpoint) {
        let connection = NWConnection(to: endpoint, using: .tcp)
        pendingResolvers.append(connection)
        let resolvedRef = ResolvedFlag()
        connection.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                let path = connection.currentPath
                if resolvedRef.flip() {
                    let ip = Self.ipString(from: path?.remoteEndpoint)
                    Task { @MainActor [weak self] in
                        self?.updateResolvedIP(for: serviceID, ip: ip)
                    }
                }
                connection.cancel()
            case .failed, .cancelled:
                Task { @MainActor [weak self] in
                    self?.pendingResolvers.removeAll { $0 === connection }
                }
            default:
                break
            }
        }
        connection.start(queue: .main)
    }

    @MainActor
    private func updateResolvedIP(for serviceID: String, ip: String?) {
        guard let ip = ip else { return }
        services = services.map { svc in
            guard svc.id == serviceID else { return svc }
            var updated = svc
            updated.resolvedIP = ip
            return updated
        }
    }

    nonisolated private static func ipString(from endpoint: NWEndpoint?) -> String? {
        guard case let .hostPort(host, _) = endpoint else { return nil }
        let raw: String
        switch host {
        case .ipv4(let addr):
            raw = "\(addr)"
        case .ipv6(let addr):
            raw = "\(addr)"
        case .name(let n, _):
            return n
        @unknown default:
            return nil
        }
        // Strip any zone identifier ("192.168.1.10%en1", "fe80::1%en0").
        // URLs don't accept the `%zone` form even though
        // IPv4Address/IPv6Address.description sometimes emits it.
        if let pct = raw.firstIndex(of: "%") {
            return String(raw[..<pct])
        }
        return raw
    }

    /// Open a tiny UDP connection toward the mDNS multicast group so
    /// iOS prompts the user for Local Network permission. Without
    /// this, NWBrowser silently returns no results on physical
    /// devices that have never granted permission.
    private func primeLocalNetworkPermission() {
        let host = NWEndpoint.Host("224.0.0.251")
        let port = NWEndpoint.Port(rawValue: 5353)!
        let params = NWParameters.udp
        let connection = NWConnection(host: host, port: port, using: params)
        connection.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready, .failed, .cancelled:
                Task { @MainActor in
                    self?.primerConnection?.cancel()
                    self?.primerConnection = nil
                }
            default:
                break
            }
        }
        connection.start(queue: .main)
        self.primerConnection = connection
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
            if !resolvingIDs.contains(name) {
                resolvingIDs.insert(name)
                resolveToIP(serviceID: name, endpoint: result.endpoint)
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
            // Preserve any previously-resolved IP across browse-result
            // refreshes (TXT updates fire `handle()` again).
            let priorIP = services.first(where: { $0.id == name })?.resolvedIP
            resolved.append(DiscoveredService(
                id: name,
                name: name,
                host: host,
                port: 7860,
                version: version,
                resolvedIP: priorIP
            ))
        }
        // De-dup + alphabetical for stable list ordering
        var seen = Set<String>()
        services = resolved
            .filter { seen.insert($0.id).inserted }
            .sorted { $0.name < $1.name }
        if !services.isEmpty {
            hasSettled = true
        }
    }
}
