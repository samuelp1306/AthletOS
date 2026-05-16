// Service Worker -- minimaler Offline-Cache fuer Screen 1.
// Strategie: stale-while-revalidate fuer das App-Shell-Bundle und
// network-first fuer /api/daily (mit Fallback auf Cache, damit der
// Tagesdaten-Block auch offline angezeigt werden kann).

const CACHE_VERSION = "perfos-v1";
const SHELL_FILES = ["/", "/index.html", "/manifest.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((c) => c.addAll(SHELL_FILES))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // API /api/daily -- network first, fallback Cache
  if (url.pathname.startsWith("/api/daily") || url.pathname.startsWith("/api/nutrition")) {
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then((c) => c.put(event.request, copy));
          return res;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Andere /api/-Routen nicht cachen
  if (url.pathname.startsWith("/api/")) {
    return;
  }

  // App Shell -- cache first
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
