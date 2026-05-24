/* AI Music Studio service worker.
 *
 * Makes the app an installable PWA (Android "Install app" + iOS home screen)
 * and caches the built app shell for instant / offline-ish loads. It NEVER
 * caches `/api` calls or non-GET requests — those always hit the network so
 * generation, vocals, and the AI request queue stay live.
 *
 * Strategy: navigations are network-first (so a fresh deploy's index.html
 * loads when online, falling back to the cached shell offline); same-origin
 * static assets are cache-first then network (hashed filenames change per
 * build, so new ones are fetched and cached on demand). Bump CACHE to force
 * a full refresh of the cached shell.
 */
const CACHE = "aimusic-shell-v1";
const SHELL = ["./", "./index.html", "./manifest.webmanifest", "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Never intercept the API or non-GET requests — always live network.
  if (req.method !== "GET" || url.pathname.startsWith("/api")) return;

  // App-shell navigations: network-first, fall back to the cached shell.
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match("./index.html")));
    return;
  }

  // Same-origin static assets: cache-first, then network (and cache it).
  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(req).then((hit) =>
        hit ||
        fetch(req).then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
          return res;
        }).catch(() => hit)
      )
    );
  }
});
