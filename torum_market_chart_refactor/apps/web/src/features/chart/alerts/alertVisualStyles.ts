import type { PriceAlertVisualStyle } from "../chartTypes";

export const DEFAULT_ALERT_VISUAL_STYLE: PriceAlertVisualStyle = {
  color: "#f5c542",
  lineStyle: "dashed",
};

export const ALERT_STYLE_STORAGE_KEY = "torum.priceAlertStyles.v1";

export function normalizeAlertVisualStyle(value: unknown): PriceAlertVisualStyle {
  if (!value || typeof value !== "object") return DEFAULT_ALERT_VISUAL_STYLE;

  const source = value as Record<string, unknown>;
  return {
    color: typeof source.color === "string" && source.color ? source.color : DEFAULT_ALERT_VISUAL_STYLE.color,
    lineStyle: source.lineStyle === "solid" ? "solid" : "dashed",
  };
}

export function loadAlertVisualStyles(): Record<string, PriceAlertVisualStyle> {
  try {
    if (typeof window === "undefined") return {};
    const raw = window.localStorage.getItem(ALERT_STYLE_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (!parsed || typeof parsed !== "object") return {};

    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).map(([id, value]) => [id, normalizeAlertVisualStyle(value)]),
    );
  } catch {
    return {};
  }
}

export function saveAlertVisualStyles(styles: Record<string, PriceAlertVisualStyle>) {
  try {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(ALERT_STYLE_STORAGE_KEY, JSON.stringify(styles));
  } catch {
    // La app puede seguir sin persistencia local.
  }
}
