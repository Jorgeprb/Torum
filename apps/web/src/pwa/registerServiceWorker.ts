export function canUseServiceWorker(): boolean {
  return "serviceWorker" in navigator && window.isSecureContext;
}

export async function ensureServiceWorkerRegistration(): Promise<ServiceWorkerRegistration> {
  if (!canUseServiceWorker()) {
    throw new Error("Service worker no disponible");
  }

  const registration = await navigator.serviceWorker.register("/sw.js");
  void registration.update().catch(() => undefined);
  return navigator.serviceWorker.ready.catch(() => registration);
}

export function registerServiceWorker(): void {
  if (!canUseServiceWorker()) {
    return;
  }

  window.addEventListener("load", () => {
    void ensureServiceWorkerRegistration().catch(() => undefined);
  });
}
