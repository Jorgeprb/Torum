import { getPushSubscriptions, getVapidPublicKey, sendPushTest, subscribePush } from "../../services/alerts";
import { canUseServiceWorker, ensureServiceWorkerRegistration } from "../../pwa/registerServiceWorker";

export type PushStatus = "unsupported" | "denied" | "permission-required" | "subscribed" | "ready" | "missing-vapid";

export function isPushSupported(): boolean {
  return canUseServiceWorker() && "PushManager" in window && "Notification" in window;
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
  const applicationServerKey = urlBase64ToArrayBuffer(publicKey);
  const registration = await ensureServiceWorkerRegistration();
  let existing = await registration.pushManager.getSubscription();
  if (existing && !subscriptionUsesKey(existing, applicationServerKey)) {
    await existing.unsubscribe();
    existing = null;
  }
  const subscription =
    existing ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey
    }));
  await subscribePush({
    ...subscription.toJSON(),
    user_agent: navigator.userAgent,
    device_name: navigator.platform || "browser"
  });
  return "subscribed";
}

export async function activatePushForPriceAlert(): Promise<PushStatus> {
  if (!isPushSupported() || Notification.permission === "denied") {
    return getPushStatus();
  }

  return activatePushNotifications();
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

function subscriptionUsesKey(subscription: PushSubscription, applicationServerKey: ArrayBuffer): boolean {
  const currentKey = subscription.options.applicationServerKey;
  if (!currentKey) {
    return true;
  }

  return arrayBuffersEqual(currentKey, applicationServerKey);
}

function arrayBuffersEqual(left: ArrayBuffer, right: ArrayBuffer): boolean {
  if (left.byteLength !== right.byteLength) {
    return false;
  }

  const leftView = new Uint8Array(left);
  const rightView = new Uint8Array(right);
  for (let index = 0; index < leftView.length; index += 1) {
    if (leftView[index] !== rightView[index]) {
      return false;
    }
  }

  return true;
}
