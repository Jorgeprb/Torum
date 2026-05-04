import { TickMarkType, type Time, type UTCTimestamp } from "lightweight-charts";

// ── Storage keys ────────────────────────────────────────────────────────────
export const chartDisplayTimeZone = "Europe/Madrid";
export const defaultChartBrokerTimeZone = "Etc/GMT-3";
export const chartBrokerTimeZoneStorageKey = "torum.chartBrokerTimeZone";
export const chartTimeModeStorageKey = "torum.chartTimeMode";
export const chartManualBrokerUtcOffsetStorageKey = "torum.chartManualBrokerUtcOffset";
export const chartManualLocalUtcOffsetStorageKey = "torum.chartManualLocalUtcOffset";
export const chartTimeSettingsChangedEvent = "torum-chart-time-settings-changed";

export type ChartTimeMode = "auto" | "manual";

// ── Timezone validation ──────────────────────────────────────────────────────
function isValidTimeZone(timeZone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone }).format(new Date(0));
    return true;
  } catch {
    return false;
  }
}

function validTimeZoneOrFallback(value: string | undefined, fallback: string): string {
  const candidate = value?.trim();
  return candidate && isValidTimeZone(candidate) ? candidate : fallback;
}

// ── Readers ─────────────────────────────────────────────────────────────────
export function readChartBrokerTimeZone(): string {
  const envValue = import.meta.env.VITE_CHART_BROKER_TIME_ZONE;

  if (typeof window === "undefined") {
    return validTimeZoneOrFallback(envValue, defaultChartBrokerTimeZone);
  }

  try {
    const storedValue = window.localStorage.getItem(chartBrokerTimeZoneStorageKey) ?? undefined;
    return validTimeZoneOrFallback(storedValue || envValue, defaultChartBrokerTimeZone);
  } catch {
    return validTimeZoneOrFallback(envValue, defaultChartBrokerTimeZone);
  }
}

export function readChartTimeMode(): ChartTimeMode {
  if (typeof window === "undefined") {
    return "auto";
  }

  try {
    return window.localStorage.getItem(chartTimeModeStorageKey) === "manual" ? "manual" : "auto";
  } catch {
    return "auto";
  }
}

// ── UTC offset helpers ───────────────────────────────────────────────────────
export function currentUtcOffsetHours(timeZone: string): number {
  const value = new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    hour12: false,
    hourCycle: "h23",
    timeZone
  }).format(new Date());
  const utcHour = new Date().getUTCHours();
  let offset = Number(value) - utcHour;

  if (offset > 12) {
    offset -= 24;
  }

  if (offset < -12) {
    offset += 24;
  }

  return offset;
}

export function readStoredUtcOffset(key: string, fallback: number): number {
  if (typeof window === "undefined") {
    return fallback;
  }

  try {
    const parsed = Number(window.localStorage.getItem(key));
    return Number.isInteger(parsed) && parsed >= -12 && parsed <= 14 ? parsed : fallback;
  } catch {
    return fallback;
  }
}

export function utcOffsetDifferenceSeconds(brokerUtcOffset: number, localUtcOffset: number): number {
  return (brokerUtcOffset - localUtcOffset) * 60 * 60;
}

// ── Formatters ───────────────────────────────────────────────────────────────
export function createTimeZonePartsFormatter(timeZone: string): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    hour: "2-digit",
    hour12: false,
    hourCycle: "h23",
    minute: "2-digit",
    month: "2-digit",
    second: "2-digit",
    timeZone,
    year: "numeric"
  });
}

export const chartBrokerTimeZone = readChartBrokerTimeZone();
export const chartBrokerTimeZoneFormatter = createTimeZonePartsFormatter(chartBrokerTimeZone);
export const chartDisplayTimeZoneFormatter = createTimeZonePartsFormatter(chartDisplayTimeZone);

export const chartCrosshairTimeFormatter = new Intl.DateTimeFormat("es-ES", {
  day: "2-digit",
  hour: "2-digit",
  hour12: false,
  hourCycle: "h23",
  minute: "2-digit",
  month: "2-digit",
  timeZone: chartDisplayTimeZone,
  year: "numeric"
});

export const chartTickYearFormatter = new Intl.DateTimeFormat("es-ES", {
  timeZone: chartDisplayTimeZone,
  year: "numeric"
});

export const chartTickMonthFormatter = new Intl.DateTimeFormat("es-ES", {
  month: "short",
  timeZone: chartDisplayTimeZone
});

export const chartTickDayFormatter = new Intl.DateTimeFormat("es-ES", {
  day: "2-digit",
  month: "2-digit",
  timeZone: chartDisplayTimeZone
});

export const chartTickTimeFormatter = new Intl.DateTimeFormat("es-ES", {
  hour: "2-digit",
  hour12: false,
  hourCycle: "h23",
  minute: "2-digit",
  timeZone: chartDisplayTimeZone
});

export const chartTickSecondsFormatter = new Intl.DateTimeFormat("es-ES", {
  hour: "2-digit",
  hour12: false,
  hourCycle: "h23",
  minute: "2-digit",
  second: "2-digit",
  timeZone: chartDisplayTimeZone
});

// ── Offset computation ───────────────────────────────────────────────────────
export function timeZoneOffsetSeconds(formatter: Intl.DateTimeFormat, utcUnixSeconds: number): number {
  const parts = formatter.formatToParts(new Date(utcUnixSeconds * 1000));
  const values: Record<string, number> = {};

  for (const part of parts) {
    if (
      part.type === "year" ||
      part.type === "month" ||
      part.type === "day" ||
      part.type === "hour" ||
      part.type === "minute" ||
      part.type === "second"
    ) {
      values[part.type] = Number(part.value);
    }
  }

  const hour = values.hour === 24 ? 0 : values.hour;
  const localAsUtcSeconds = Math.floor(
    Date.UTC(
      values.year ?? 1970,
      (values.month ?? 1) - 1,
      values.day ?? 1,
      hour ?? 0,
      values.minute ?? 0,
      values.second ?? 0
    ) / 1000
  );

  return localAsUtcSeconds - Math.floor(utcUnixSeconds);
}

export function manualBrokerLocalOffsetSeconds(): number {
  return utcOffsetDifferenceSeconds(
    readStoredUtcOffset(chartManualBrokerUtcOffsetStorageKey, currentUtcOffsetHours(chartBrokerTimeZone)),
    readStoredUtcOffset(chartManualLocalUtcOffsetStorageKey, currentUtcOffsetHours(chartDisplayTimeZone))
  );
}

export function chartBrokerOffsetSeconds(utcUnixSeconds: number): number {
  if (readChartTimeMode() === "manual") {
    return timeZoneOffsetSeconds(chartDisplayTimeZoneFormatter, utcUnixSeconds) + manualBrokerLocalOffsetSeconds();
  }

  return timeZoneOffsetSeconds(chartBrokerTimeZoneFormatter, utcUnixSeconds);
}

export function utcToBrokerChartTime(utcUnixSeconds: number): number {
  return Math.floor(utcUnixSeconds + chartBrokerOffsetSeconds(utcUnixSeconds));
}

export function brokerChartTimeToUtc(chartUnixSeconds: number): number {
  let utcUnixSeconds = chartUnixSeconds - chartBrokerOffsetSeconds(chartUnixSeconds);

  for (let iteration = 0; iteration < 3; iteration += 1) {
    utcUnixSeconds = chartUnixSeconds - chartBrokerOffsetSeconds(utcUnixSeconds);
  }

  return Math.floor(utcUnixSeconds);
}

export function chartTimeToDisplayDate(time: Time): Date {
  return new Date(brokerChartTimeToUtc(timeToNumber(time)) * 1000);
}

export function formatChartCrosshairTime(time: Time): string {
  return chartCrosshairTimeFormatter.format(chartTimeToDisplayDate(time));
}

export function formatChartTickMark(time: Time, tickMarkType: TickMarkType): string {
  const displayDate = chartTimeToDisplayDate(time);

  if (tickMarkType === TickMarkType.Year) {
    return chartTickYearFormatter.format(displayDate);
  }

  if (tickMarkType === TickMarkType.Month) {
    return chartTickMonthFormatter.format(displayDate).replace(".", "");
  }

  if (tickMarkType === TickMarkType.DayOfMonth) {
    return chartTickDayFormatter.format(displayDate);
  }

  if (tickMarkType === TickMarkType.TimeWithSeconds) {
    return chartTickSecondsFormatter.format(displayDate);
  }

  return chartTickTimeFormatter.format(displayDate);
}

// ── Time arithmetic ──────────────────────────────────────────────────────────
export function normalizeUnixSeconds(value: unknown): UTCTimestamp | null {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      return null;
    }

    const seconds = value > 10_000_000_000 ? Math.floor(value / 1000) : Math.floor(value);
    return seconds as UTCTimestamp;
  }

  if (typeof value === "string") {
    const parsedAsNumber = Number(value);

    if (Number.isFinite(parsedAsNumber)) {
      const seconds = parsedAsNumber > 10_000_000_000 ? Math.floor(parsedAsNumber / 1000) : Math.floor(parsedAsNumber);
      return seconds as UTCTimestamp;
    }

    const parsedDate = Date.parse(value);

    if (!Number.isNaN(parsedDate)) {
      return Math.floor(parsedDate / 1000) as UTCTimestamp;
    }
  }

  return null;
}

export function timeToNumber(time: Time): number {
  if (typeof time === "number") {
    return time;
  }

  if (typeof time === "string") {
    const parsed = Date.parse(time);
    return Number.isNaN(parsed) ? 0 : Math.floor(parsed / 1000);
  }

  return Math.floor(Date.UTC(time.year, time.month - 1, time.day) / 1000);
}

export function timeframeToSeconds(timeframe: string): number {
  switch (timeframe) {
    case "M1":
      return 60;
    case "M5":
      return 5 * 60;
    case "H1":
      return 60 * 60;
    case "H2":
      return 2 * 60 * 60;
    case "H3":
      return 3 * 60 * 60;
    case "H4":
      return 4 * 60 * 60;
    case "D1":
      return 24 * 60 * 60;
    case "W1":
      return 7 * 24 * 60 * 60;
    default:
      return 60;
  }
}

export function timeframeBucketStart(unixSeconds: number, timeframe: string): number {
  const date = new Date(unixSeconds * 1000);

  const year = date.getUTCFullYear();
  const month = date.getUTCMonth();
  const day = date.getUTCDate();
  const hour = date.getUTCHours();
  const minute = date.getUTCMinutes();

  if (timeframe === "M1") {
    return Math.floor(Date.UTC(year, month, day, hour, minute, 0, 0) / 1000);
  }

  if (timeframe === "M5") {
    const bucketMinute = Math.floor(minute / 5) * 5;
    return Math.floor(Date.UTC(year, month, day, hour, bucketMinute, 0, 0) / 1000);
  }

  if (timeframe === "H1") {
    return Math.floor(Date.UTC(year, month, day, hour, 0, 0, 0) / 1000);
  }

  if (timeframe === "H2") {
    const bucketHour = Math.floor(hour / 2) * 2;
    return Math.floor(Date.UTC(year, month, day, bucketHour, 0, 0, 0) / 1000);
  }

  if (timeframe === "H3") {
    const bucketHour = Math.floor(hour / 3) * 3;
    return Math.floor(Date.UTC(year, month, day, bucketHour, 0, 0, 0) / 1000);
  }

  if (timeframe === "H4") {
    const bucketHour = Math.floor(hour / 4) * 4;
    return Math.floor(Date.UTC(year, month, day, bucketHour, 0, 0, 0) / 1000);
  }

  if (timeframe === "D1") {
    return Math.floor(Date.UTC(year, month, day, 0, 0, 0, 0) / 1000);
  }

  if (timeframe === "W1") {
    const startOfDay = Date.UTC(year, month, day, 0, 0, 0, 0);
    const utcDay = new Date(startOfDay).getUTCDay();
    const daysFromMonday = utcDay === 0 ? 6 : utcDay - 1;
    return Math.floor((startOfDay - daysFromMonday * 24 * 60 * 60 * 1000) / 1000);
  }

  return unixSeconds;
}

export function findNearestCandleTime(targetTime: number, candleTimes: number[]): number | null {
  if (candleTimes.length === 0) {
    return null;
  }

  let bestTime = candleTimes[0];
  let bestDistance = Math.abs(bestTime - targetTime);

  for (const candleTime of candleTimes) {
    const distance = Math.abs(candleTime - targetTime);

    if (distance < bestDistance) {
      bestTime = candleTime;
      bestDistance = distance;
    }
  }

  return bestTime;
}

export function markerTimeToChartTime(markerTime: Time, timeframe: string, candleTimes: number[]): UTCTimestamp | null {
  const rawTime = timeToNumber(markerTime);

  if (!Number.isFinite(rawTime) || rawTime <= 0) {
    return null;
  }

  const bucketTime = timeframeBucketStart(rawTime, timeframe);

  if (candleTimes.includes(bucketTime)) {
    return bucketTime as UTCTimestamp;
  }

  const nearestTime = findNearestCandleTime(bucketTime, candleTimes);

  if (nearestTime === null) {
    return null;
  }

  const maxDistance = timeframeToSeconds(timeframe);

  if (Math.abs(nearestTime - bucketTime) > maxDistance) {
    return null;
  }

  return nearestTime as UTCTimestamp;
}
