export function createRequestId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `torum-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}
