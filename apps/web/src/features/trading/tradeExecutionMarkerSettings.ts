export const tradeExecutionMarkersChangedEvent = "torum-trade-execution-markers-changed";

const showTradeExecutionMarkersStorageKey = "torum.showTradeExecutionMarkers";
const tradeExecutionMarkersOnlyM5StorageKey = "torum.tradeExecutionMarkersOnlyM5";

export interface TradeExecutionMarkerSettings {
  show_trade_execution_markers: boolean;
  trade_execution_markers_only_m5: boolean;
}

export function readTradeExecutionMarkerSettings(): TradeExecutionMarkerSettings {
  try {
    return {
      show_trade_execution_markers: window.localStorage.getItem(showTradeExecutionMarkersStorageKey) !== "0",
      trade_execution_markers_only_m5: window.localStorage.getItem(tradeExecutionMarkersOnlyM5StorageKey) !== "0"
    };
  } catch {
    return {
      show_trade_execution_markers: true,
      trade_execution_markers_only_m5: true
    };
  }
}

export function saveTradeExecutionMarkerSetting<K extends keyof TradeExecutionMarkerSettings>(
  key: K,
  value: TradeExecutionMarkerSettings[K]
): TradeExecutionMarkerSettings {
  try {
    if (key === "show_trade_execution_markers") {
      window.localStorage.setItem(showTradeExecutionMarkersStorageKey, value ? "1" : "0");
    } else {
      window.localStorage.setItem(tradeExecutionMarkersOnlyM5StorageKey, value ? "1" : "0");
    }
    window.dispatchEvent(new Event(tradeExecutionMarkersChangedEvent));
  } catch {
    // Visual preference only.
  }
  return readTradeExecutionMarkerSettings();
}
