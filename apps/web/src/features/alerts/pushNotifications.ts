import { getPushSubscriptions, getVapidPublicKey, sendPushTest, subscribePush } from "../../services/alerts";

export type PushStatus = "unsupported" | "denied" | "permission-required" | "subscribed" | "ready" | "missing-vapid";

export function isPushSupported(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

export function currentPushPermission(): NotificationPermission | "unsupported" {
  return "Notification" in window ? Notification.permission : "unsupported";
}

export async function getPushStatus(): Promise<PushStatus> {
  if (!isPushSupported()) {
    return "unsupported";
  }
  if (Notification.permission === "denied") {
    return "denied";
  }
  const subscriptions = await getPushSubscriptions().catch(() => []);
  if (subscriptions.some((subscription) => subscription.enabled)) {
    return "subscribed";
  }
  return Notification.permission === "granted" ? "ready" : "permission-required";
}

export async function activatePushNotifications(): Promise<PushStatus> {
  if (!isPushSupported()) {
    return "unsupported";
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    return permission === "denied" ? "denied" : "permission-required";
  }

  const { public_key: publicKey } = await getVapidPublicKey();
  if (!publicKey) {
    return "missing-vapid";
  }
  const registration = await navigator.serviceWorker.register("/sw.js");
  const existing = await registration.pushManager.getSubscription();
  const subscription =
    existing ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToArrayBuffer(publicKey)
    }));
  await subscribePush({
    ...subscription.toJSON(),
    user_agent: navigator.userAgent,
    device_name: navigator.platform || "browser"
  });
  return "subscribed";
}

export async function sendTestPushNotification() {
  return sendPushTest();
}

function urlBase64ToArrayBuffer(base64String: string): ArrayBuffer {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let index = 0; index < rawData.length; index += 1) {
    outputArray[index] = rawData.charCodeAt(index);
  }
  return outputArray.buffer.slice(outputArray.byteOffset, outputArray.byteOffset + outputArray.byteLength);
}
