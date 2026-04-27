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
