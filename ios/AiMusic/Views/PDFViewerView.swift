//
//  PDFViewerView.swift
//  AiMusic
//
//  Full-screen native score viewer, presented over the WebView when a
//  /pdf/full or /pdf/part/… link is tapped in the Studio UI. It toggles
//  between the full score and each instrument part (from /api/blocks/<name>/
//  parts), and offers share / save-to-Files and save-to-Library. The PDFs are
//  fetched with the app's auth token (PDFDocument(url:) can't send headers),
//  so downloads work over Tailscale/LAN just like the WebView.
//

import SwiftUI
import PDFKit

/// One score view — the full score or a single instrument part.
struct ScorePart: Identifiable, Decodable, Hashable {
    let id: String
    let name: String
    let url: String   // server-relative, e.g. "/api/blocks/<name>/pdf/full"
}

private struct PartsResponse: Decodable { let parts: [ScorePart] }

struct PDFViewerScreen: View {
    let blockName: String      // decoded display name (also the library id)
    let baseURL: URL           // scheme://host[:port]
    let token: String

    @Environment(\.dismiss) private var dismiss
    @State private var parts: [ScorePart] = []
    @State private var selectedPartID: String
    @State private var currentURL: URL
    @State private var document: PDFDocument?
    @State private var loading = true
    @State private var errorText: String?
    @State private var localFileURL: URL?
    @State private var showShare = false
    @State private var saveState: SaveState = .idle

    enum SaveState { case idle, saving, saved, error }

    init(blockName: String, baseURL: URL, token: String, initialPartURL: URL) {
        self.blockName = blockName
        self.baseURL = baseURL
        self.token = token
        _currentURL = State(initialValue: initialPartURL)
        _selectedPartID = State(initialValue: PDFViewerScreen.partID(from: initialPartURL))
    }

    var body: some View {
        NavigationStack {
            content
                .navigationTitle(blockName)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { toolbar }
                .sheet(isPresented: $showShare) {
                    if let localFileURL { ShareSheet(items: [localFileURL]) }
                }
                .task { await loadParts() }
                .task(id: currentURL) { await loadPDF() }
        }
    }

    @ViewBuilder private var content: some View {
        if let document {
            PDFKitView(document: document).ignoresSafeArea(edges: .bottom)
        } else if loading {
            ProgressView("Loading score…")
        } else {
            ContentUnavailableView(
                "Couldn't load the score",
                systemImage: "doc.richtext",
                description: Text(errorText ?? "The PDF failed to load."))
        }
    }

    @ToolbarContentBuilder private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Button("Done") { dismiss() }
        }
        ToolbarItemGroup(placement: .topBarTrailing) {
            // Instrument-track toggle — full score plus one entry per part.
            if parts.count > 1 {
                Picker("Instrument", selection: $selectedPartID) {
                    ForEach(parts) { Text($0.name).tag($0.id) }
                }
                .pickerStyle(.menu)
                .onChange(of: selectedPartID) { _, id in
                    if let part = parts.first(where: { $0.id == id }),
                       let abs = absoluteURL(part.url) {
                        currentURL = abs
                    }
                }
            }
            Menu {
                Button { showShare = true } label: {
                    Label("Share / Save to Files", systemImage: "square.and.arrow.up")
                }.disabled(localFileURL == nil)
                Button { Task { await saveToLibrary() } } label: {
                    Label(saveLabel, systemImage: saveState == .saved ? "checkmark" : "star")
                }.disabled(saveState == .saving || saveState == .saved)
            } label: {
                Image(systemName: "ellipsis.circle")
            }
        }
    }

    private var saveLabel: String {
        switch saveState {
        case .idle:   return "Save to Library"
        case .saving: return "Saving…"
        case .saved:  return "Saved"
        case .error:  return "Retry save"
        }
    }

    // MARK: - Networking

    private func request(_ url: URL, method: String = "GET",
                         jsonBody: [String: Any]? = nil) -> URLRequest {
        var r = URLRequest(url: url)
        r.httpMethod = method
        if let jsonBody {
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try? JSONSerialization.data(withJSONObject: jsonBody)
        }
        return NetworkManager.shared.authorized(r, token: token)
    }

    private func absoluteURL(_ serverRelative: String) -> URL? {
        URL(string: baseURL.absoluteString + serverRelative)
    }

    @MainActor private func loadPDF() async {
        loading = true
        errorText = nil
        do {
            let (data, resp) = try await NetworkManager.shared.session.data(for: request(currentURL))
            guard let http = resp as? HTTPURLResponse, http.statusCode == 200,
                  let doc = PDFDocument(data: data) else {
                throw NSError(domain: "PDFViewer",
                              code: (resp as? HTTPURLResponse)?.statusCode ?? -1,
                              userInfo: [NSLocalizedDescriptionKey: "Server returned no PDF."])
            }
            document = doc
            let tmp = FileManager.default.temporaryDirectory
                .appendingPathComponent("\(fileStem).pdf")
            try? data.write(to: tmp)
            localFileURL = tmp
        } catch {
            document = nil
            errorText = error.localizedDescription
        }
        loading = false
    }

    @MainActor private func loadParts() async {
        guard let encoded = blockName.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed),
              let url = absoluteURL("/api/blocks/\(encoded)/parts") else { return }
        do {
            let (data, _) = try await NetworkManager.shared.session.data(for: request(url))
            parts = try JSONDecoder().decode(PartsResponse.self, from: data).parts
        } catch {
            // Non-fatal: the toggle just won't appear; the tapped PDF still shows.
        }
    }

    @MainActor private func saveToLibrary() async {
        guard let url = absoluteURL("/api/library") else { return }
        saveState = .saving
        do {
            let (_, resp) = try await NetworkManager.shared.session.data(
                for: request(url, method: "POST", jsonBody: ["block_name": blockName]))
            saveState = (resp as? HTTPURLResponse)?.statusCode == 200 ? .saved : .error
        } catch {
            saveState = .error
        }
    }

    private var fileStem: String {
        "\(blockName.replacingOccurrences(of: "/", with: "_"))-\(selectedPartID)"
    }

    /// Derive the part id from a /pdf/full or /pdf/part/<id> URL.
    static func partID(from url: URL) -> String {
        let comps = url.path(percentEncoded: false).split(separator: "/").map(String.init)
        if let i = comps.firstIndex(of: "part"), i + 1 < comps.count {
            return comps[i + 1]
        }
        return "full"
    }
}

/// Wraps PDFKit's PDFView for SwiftUI.
struct PDFKitView: UIViewRepresentable {
    let document: PDFDocument

    func makeUIView(context: Context) -> PDFView {
        let view = PDFView()
        view.autoScales = true
        view.displayMode = .singlePageContinuous
        view.displayDirection = .vertical
        view.document = document
        return view
    }

    func updateUIView(_ view: PDFView, context: Context) {
        if view.document !== document { view.document = document }
    }
}

/// UIActivityViewController bridge for share / save-to-Files.
struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
