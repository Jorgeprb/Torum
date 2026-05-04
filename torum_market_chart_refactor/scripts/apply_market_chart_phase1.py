from __future__ import annotations

from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "apps/web/src/features/chart/MarketChart.tsx"

IMPORT_BLOCK = '''
import type {
  ChartLineStyle,
  MarketChartProps,
  PriceAlertOverlay,
  PriceAlertVisualStyle,
  PullbackDebugOverlay,
  TradeLine,
  TradeLineOverlay,
  TradeMarker,
  TradeMarkerOverlay,
  ZoneOverlay,
} from "./chartTypes";
export type { TradeLine, TradeMarker } from "./chartTypes";
import {
  chartTimeSettingsChangedEvent,
  findNearestCandleTime,
  formatChartCrosshairTime,
  formatChartTickMark,
  markerTimeToChartTime,
  normalizeUnixSeconds,
  readChartTimeMode,
  timeToNumber,
  timeframeBucketStart,
  timeframeToSeconds,
  utcToBrokerChartTime,
} from "./chartTime";
import {
  candleTimeValues,
  chartTimeToUnix,
  isValidOhlc,
  normalizeCandlesForChart,
  numberValue,
  payloadsEqual,
  sortCandlesByTimeAsc,
  sortLineDataByTimeAsc,
  toChartCandle,
} from "./chartData";
import {
  barsWithCandleSpacing,
  buildFuturePaddingData,
  calculateVisibleBarsForWidth,
  centerRecentBars,
  centerSymbolChange,
  disablePriceAutoScale,
  hardResetChartView,
  initialCandleBarSpacing,
  isNewsZoneVisibleNow,
  maxVisibleBarsByTimeframe,
  newsZoneEnd,
  newsZoneEndUtc,
  newsZoneStart,
  newsZoneStartUtc,
  resetPriceScale,
  scrollToLatestRealCandle,
} from "./chartView";
import { chartXToTime, cssPixelValue, lowerBound, timeToChartX } from "./chartCoordinates";
import { clampNumber, clampedNumericStyleValue, colorInputValue, cssLineStyle, hexToRgba, lineStyleValue } from "./chartStyle";
import { tradeLineLabel } from "./tradeLineLabel";
import { DEFAULT_ALERT_VISUAL_STYLE, loadAlertVisualStyles, normalizeAlertVisualStyle, saveAlertVisualStyles } from "./alerts/alertVisualStyles";
import { canBeTorumV1OperationZone, isTorumV1OperationZone } from "./drawings/torumZones";
import { drawingTimeSpanFromPoints } from "./drawings/drawingGeometry";
'''.strip()

INTERFACES_AND_TYPES = [
    "MarketChartProps",
    "ZoneOverlay",
    "TradeLine",
    "TradeMarker",
    "PriceAlertVisualStyle",
    "TradeLineOverlay",
    "TradeMarkerOverlay",
    "PriceAlertOverlay",
    "PullbackDebugOverlay",
]

TYPE_ALIASES = ["ChartLineStyle", "ChartTimeMode"]

CONSTS = [
    "DEFAULT_ALERT_VISUAL_STYLE",
    "ALERT_STYLE_STORAGE_KEY",
    "chartDisplayTimeZone",
    "defaultChartBrokerTimeZone",
    "chartBrokerTimeZoneStorageKey",
    "chartTimeModeStorageKey",
    "chartManualBrokerUtcOffsetStorageKey",
    "chartManualLocalUtcOffsetStorageKey",
    "chartTimeSettingsChangedEvent",
    "chartBrokerTimeZone",
    "chartBrokerTimeZoneFormatter",
    "chartDisplayTimeZoneFormatter",
    "chartCrosshairTimeFormatter",
    "chartTickYearFormatter",
    "chartTickMonthFormatter",
    "chartTickDayFormatter",
    "chartTickTimeFormatter",
    "chartTickSecondsFormatter",
    "desiredCandleSpacingPx",
    "initialCandleBarSpacing",
    "minVisibleBars",
    "maxVisibleBarsByTimeframe",
]

FUNCTIONS = [
    "normalizeUnixSeconds",
    "isValidTimeZone",
    "validTimeZoneOrFallback",
    "readChartBrokerTimeZone",
    "readChartTimeMode",
    "currentUtcOffsetHours",
    "readStoredUtcOffset",
    "utcOffsetDifferenceSeconds",
    "createTimeZonePartsFormatter",
    "timeZoneOffsetSeconds",
    "manualBrokerLocalOffsetSeconds",
    "chartBrokerOffsetSeconds",
    "utcToBrokerChartTime",
    "brokerChartTimeToUtc",
    "chartTimeToDisplayDate",
    "formatChartCrosshairTime",
    "formatChartTickMark",
    "isValidOhlc",
    "toChartCandle",
    "timeToNumber",
    "timeframeToSeconds",
    "timeframeBucketStart",
    "findNearestCandleTime",
    "markerTimeToChartTime",
    "sortCandlesByTimeAsc",
    "normalizeCandlesForChart",
    "sortLineDataByTimeAsc",
    "numberValue",
    "payloadsEqual",
    "tradeLineLabel",
    "clampNumber",
    "clampedNumericStyleValue",
    "lineStyleValue",
    "cssLineStyle",
    "hexToRgba",
    "colorInputValue",
    "normalizeAlertVisualStyle",
    "isTorumV1OperationZone",
    "canBeTorumV1OperationZone",
    "loadAlertVisualStyles",
    "saveAlertVisualStyles",
    "cssPixelValue",
    "chartTimeToUnix",
    "candleTimeValues",
    "lowerBound",
    "timeToChartX",
    "chartXToTime",
    "drawingTimeSpanFromPoints",
    "barsWithCandleSpacing",
    "calculateVisibleBarsForWidth",
    "centerRecentBars",
    "scrollToLatestRealCandle",
    "lastRealCandleTime",
    "lastRealCandleClose",
    "newsZoneStartUtc",
    "newsZoneEndUtc",
    "newsZoneStart",
    "newsZoneEnd",
    "isNewsZoneVisibleNow",
    "buildFuturePaddingData",
    "resetPriceScale",
    "disablePriceAutoScale",
    "hardResetChartView",
    "centerSymbolChange",
]


def remove_balanced_declaration(source: str, keyword_pattern: str, name: str) -> tuple[str, bool]:
    # Works for top-level interface/type-like declarations with one balanced { ... } body.
    pattern = re.compile(rf"(?:export\s+)?{keyword_pattern}\s+{re.escape(name)}\b[^{{;=]*{{", re.MULTILINE)
    match = pattern.search(source)
    if not match:
        return source, False

    brace_start = source.find("{", match.start())
    depth = 0
    index = brace_start
    while index < len(source):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                while end < len(source) and source[end] in " \t\r\n;":
                    end += 1
                return source[: match.start()] + source[end:], True
        index += 1
    return source, False


def remove_type_alias(source: str, name: str) -> tuple[str, bool]:
    pattern = re.compile(rf"(?:export\s+)?type\s+{re.escape(name)}\b[^;]*;\s*", re.DOTALL)
    return pattern.subn("", source, count=1)


def remove_const(source: str, name: str) -> tuple[str, bool]:
    pattern = re.compile(rf"const\s+{re.escape(name)}\b[\s\S]*?;\s*", re.MULTILINE)
    return pattern.subn("", source, count=1)


def remove_function(source: str, name: str) -> tuple[str, bool]:
    match = re.search(rf"function\s+{re.escape(name)}\s*\(", source)
    if not match:
        return source, False

    brace_start = source.find("{", match.end())
    if brace_start < 0:
        return source, False

    depth = 0
    index = brace_start
    in_string: str | None = None
    escaped = False
    while index < len(source):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
        else:
            if char in ('"', "'", "`"):
                in_string = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    while end < len(source) and source[end] in " \t\r\n;":
                        end += 1
                    return source[: match.start()] + source[end:], True
        index += 1
    return source, False


def insert_import_block(source: str) -> str:
    if "./chartTypes" in source:
        return source

    first_non_import = re.search(r"\binterface\s+MarketChartProps\b|\bfunction\s+normalizeUnixSeconds\b", source)
    if first_non_import:
        index = first_non_import.start()
        return source[:index] + "\n" + IMPORT_BLOCK + "\n" + source[index:]

    # Fallback: append after last import statement.
    matches = list(re.finditer(r"^import\s+[\s\S]*?;", source, re.MULTILINE))
    if matches:
        last = matches[-1]
        return source[: last.end()] + "\n" + IMPORT_BLOCK + source[last.end():]

    return IMPORT_BLOCK + "\n" + source


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"No existe {TARGET}. Ejecuta el script desde la raíz del repo Torum.")

    backup = TARGET.with_suffix(".tsx.before-refactor-phase1")
    if not backup.exists():
        shutil.copy2(TARGET, backup)

    source = TARGET.read_text(encoding="utf-8")
    source = insert_import_block(source)

    removed: list[str] = []
    missing: list[str] = []

    for name in INTERFACES_AND_TYPES:
        source, ok = remove_balanced_declaration(source, "interface", name)
        (removed if ok else missing).append(f"interface {name}")

    for name in TYPE_ALIASES:
        source, count = remove_type_alias(source, name)
        (removed if count else missing).append(f"type {name}")

    for name in CONSTS:
        source, count = remove_const(source, name)
        (removed if count else missing).append(f"const {name}")

    for name in FUNCTIONS:
        source, ok = remove_function(source, name)
        (removed if ok else missing).append(f"function {name}")

    # Optional: remove now-unused TickMarkType if present in lightweight-charts import.
    source = source.replace(", TickMarkType", "")
    source = source.replace("TickMarkType, ", "")

    TARGET.write_text(source, encoding="utf-8")

    print(f"Backup creado: {backup}")
    print(f"Modificado: {TARGET}")
    print(f"Declaraciones movidas: {len(removed)}")
    if missing:
        print("No encontradas o ya movidas:")
        for item in missing:
            print(f"  - {item}")
    print("\nAhora ejecuta: pnpm -C apps/web typecheck  (o npm run build según tu setup)")


if __name__ == "__main__":
    main()
