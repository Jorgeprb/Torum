const CACHE_NAME = "torum-shell-v2";
const SHELL_ASSETS = ["/", "/manifest.webmanifest", "/pwa-icon.svg"];
self.__WB_MANIFEST;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") {
    return;
  }

  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request).then((response) => response || caches.match("/")))
  );
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = {};
  }

  const title = payload.title || "Torum";
  const options = {
    body: payload.body || "Nueva alerta de Torum",
    icon: "/pwa-icon-192.png",
    badge: "/pwa-icon-192.png",
    data: payload.data || {},
    tag: payload.data?.alert_id || "torum-alert",
    renotify: false
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const symbol = event.notification.data?.symbol;
  const url = symbol ? `/?symbol=${encodeURIComponent(symbol)}` : "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ("focus" in client) {
          client.postMessage({ type: "price_alert_notification_click", symbol });
          return client.focus();
        }
      }
      return self.clients.openWindow(url);
    })
  );
});
