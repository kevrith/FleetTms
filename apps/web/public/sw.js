/* Keeps the app's own files so FleetTms opens without a network. Business data is not kept here: the app saves that itself
   (see src/readCache.ts) and the API lives on another address, which this worker never touches. The build step fills in the
   two placeholders below, so every release gets a fresh cache and the old one is deleted. */
const CACHE = "fleettms-__BUILD__";
const PRECACHE = ["__PRECACHE__"];
// A host may add "Vary: Origin"; a saved file must still match when a script is requested with an Origin header.
const SAME = { ignoreVary: true };

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => Promise.all(PRECACHE.map((url) => cache.add(url).catch(() => undefined))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname === "/sw.js")
    return;

  // Every page is the same app shell. Ask the network first so a release shows up, fall back to the saved shell offline.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            void caches.open(CACHE).then((c) => c.put("/", copy));
          }
          return res;
        })
        .catch(() => caches.match("/", SAME).then((hit) => hit ?? Response.error())),
    );
    return;
  }

  // Built files have the content in their name, so a saved copy is always right.
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(
      caches.match(request, SAME).then(
        (hit) =>
          hit ??
          fetch(request).then((res) => {
            if (res.ok) {
              const copy = res.clone();
              void caches.open(CACHE).then((c) => c.put(request, copy));
            }
            return res;
          }),
      ),
    );
    return;
  }

  // Icons and the manifest: show the saved one at once and refresh it in the background.
  event.respondWith(
    caches.match(request, SAME).then((hit) => {
      const fresh = fetch(request)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            void caches.open(CACHE).then((c) => c.put(request, copy));
          }
          return res;
        })
        .catch(() => hit ?? Response.error());
      return hit ?? fresh;
    }),
  );
});
