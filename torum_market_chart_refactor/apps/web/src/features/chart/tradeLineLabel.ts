import type { TradeLine } from "./chartTypes";

export function tradeLineLabel(line: TradeLine, price: number): string {
  if (
    line.tone === "tp" &&
    typeof line.openPrice === "number" &&
    Number.isFinite(line.openPrice) &&
    line.openPrice !== 0 &&
    typeof line.volume === "number" &&
    typeof line.contractSize === "number"
  ) {
    const direction = line.side === "SELL" ? -1 : 1;
    const tpPercent = ((price - line.openPrice) / line.openPrice) * 100 * direction;
    const profit = (price - line.openPrice) * line.volume * line.contractSize * direction;
    return `TP, ${profit >= 0 ? "+" : ""}${profit.toFixed(2)} ${line.currency ?? ""}, ${tpPercent.toFixed(2)}%`;
  }

  return line.label;
}
