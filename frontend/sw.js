/* Service worker: la app abre sin conexión y los datos quedan en caché. */
const VERSION = "obra-v1";
const ESTATICOS = [
  "/", "/index.html", "/styles.css", "/app.js", "/config.js",
  "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(ESTATICOS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((claves) => Promise.all(claves.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;

  // Datos: red primero, caché como respaldo (el usuario ve lo último conocido).
  if (url.pathname.startsWith("/api/")) {
    e.respondWith(
      fetch(e.request)
        .then((r) => {
          const copia = r.clone();
          caches.open(VERSION).then((c) => c.put(e.request, copia));
          return r;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Estáticos: caché primero.
  e.respondWith(
    caches.match(e.request).then(
      (hit) =>
        hit ||
        fetch(e.request).then((r) => {
          const copia = r.clone();
          if (r.ok) caches.open(VERSION).then((c) => c.put(e.request, copia));
          return r;
        }).catch(() => caches.match("/index.html"))
    )
  );
});
