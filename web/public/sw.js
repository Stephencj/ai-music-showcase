/* AI Music Studio service worker.
 *
 * Makes the app an installable PWA (Android "Install app" + iOS home screen)
 * and caches the built app shell for instant / offline-ish loads. It NEVER
 * caches `/api` calls or non-GET requests — those always hit the network so
 * generation, vocals, and the AI request queue stay live.
 *
 * Strategy: navigations are network-first AND refresh the cached shell on
 * every successful load (so the offline fallback never goes stale); same-origin
 * static assets are cache-first then network (hashed filenames change per
 * build, so new ones are fetched and cached on demand). `skipWaiting` +
 * `clients.claim` + a `controllerchange` reload in main.tsx mean a new deploy
 * takes over and refreshes the open app automatically.
 *
 * Bump CACHE on every shell-affecting change — it both forces this script's
 * bytes to change (so the browser detects the update) and drops the old
 * cache (stale shell + old hashed assets) in `activate`.
 */
const CACHE = "aimusic-shell-v2";
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

// Let the page tell a waiting worker to take over immediately.
self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Never intercept the API or non-GET requests — always live network.
  if (req.method !== "GET" || url.pathname.startsWith("/api")) return;

  // App-shell navigations: network-first; on success refresh the cached
  // index.html so the offline fallback stays current, else fall back to it.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put("./index.html", copy));
          return res;
        })
        .catch(() => caches.match("./index.html").then((m) => m || caches.match("./")))
    );
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
