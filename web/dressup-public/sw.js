/* Dress Up Band — offline-first service worker. The whole app is static
 * (no backend), so cache everything and serve from cache, updating in the
 * background. Bump CACHE to force a refresh of cached assets. */
const CACHE = "dressup-v1";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(["./", "./index.html"])).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  // Navigations: cache-first on the shell so it opens instantly offline.
  if (req.mode === "navigate") {
    e.respondWith(caches.match("./index.html").then((m) => m || fetch(req)));
    return;
  }
  e.respondWith(
    caches.match(req).then((hit) =>
      hit || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        return res;
      }).catch(() => hit)
    )
  );
});
