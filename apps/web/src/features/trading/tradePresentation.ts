import type { Time } from "lightweight-charts";

import type { TradeExecutionMarker, TradeLine, TradeMarker } from "../chart/MarketChart";
import type { SymbolMapping, Timeframe } from "../../services/market";
import type { PositionRead, TradeHistoryItem } from "../../services/trading";
import type { TradeExecutionMarkerSettings } from "./tradeExecutionMarkerSettings";

export function isReallyOpenPosition(position: PositionRead): boolean {
  if (position.status !== "OPEN") {
    return false;
  }

  if (position.closed_at) {
    return false;
  }

  if (position.close_price !== null && position.close_price !== undefined) {
    return false;
  }

  if (position.mode !== "PAPER" && position.mt5_position_ticket === null) {
    return false;
  }

  return true;
}

export function uniqueMarkers(markers: TradeMarker[]): TradeMarker[] {
  const seen = new Set<string>();

  return markers.filter((marker) => {
    const key = marker.id;

    if (seen.has(key)) {
      return false;
    }

    seen.add(key);
    return true;
  });
}

export function positionOpenTime(position: PositionRead | TradeHistoryItem): Time {
  const timeMs = position.open_time_msc ?? new Date(position.opened_at).getTime();
  return Math.floor(timeMs / 1000) as Time;
}

export function positionCloseTime(position: PositionRead | TradeHistoryItem): Time | null {
  const timeMs = position.close_time_msc ?? (position.closed_at ? new Date(position.closed_at).getTime() : null);
  return timeMs === null ? null : Math.floor(timeMs / 1000) as Time;
}

export interface TradeExecutionSource {
  accountLogin: number | null;
  accountServer: string | null;
  closePrice: number | null;
  closedAt: string | null;
  closeTimeMsc: number | null;
  internalSymbol: string;
  mode: string;
  mt5PositionTicket: number | null;
  openPrice: number;
  openedAt: string;
  openTimeMsc: number | null;
  enrichmentStatus: string | null;
  orderId: number | null;
  positionId: number;
  side: "BUY" | "SELL";
  status: "OPEN" | "CLOSED";
  volume: number;
}

export function tradeExecutionSourceAliases(source: TradeExecutionSource): string[] {
  const account = `${source.accountLogin ?? "unknown"}:${source.accountServer ?? "unknown"}`;
  const aliases = [`position:${source.positionId}`];
  if (source.mt5PositionTicket) aliases.push(`mt5:${account}:${source.mt5PositionTicket}`);
  if (source.orderId) aliases.push(`order:${source.orderId}`);

  const openedMs = source.openTimeMsc ?? Date.parse(source.openedAt);
  if (Number.isFinite(openedMs)) {
    const timeBucket = Math.round(openedMs / 2000);
    const priceKey = Number.isFinite(source.openPrice) ? source.openPrice.toFixed(4) : "unknown-price";
    const volumeKey = Number.isFinite(source.volume) ? source.volume.toFixed(4) : "unknown-volume";
    aliases.push(`fuzzy:${account}:${source.internalSymbol}:${source.side}:${timeBucket}:${priceKey}:${volumeKey}`);
  }
  return aliases;
}

export function tradeExecutionSourceId(source: TradeExecutionSource): string {
  const account = `${source.accountLogin ?? "unknown"}:${source.accountServer ?? "unknown"}`;
  if (source.mt5PositionTicket) return `mt5:${account}:${source.mt5PositionTicket}`;
  if (source.orderId) return `order:${source.orderId}`;
  return `position:${source.positionId}`;
}

export function tradeExecutionSourceScore(source: TradeExecutionSource): number {
  let score = source.status === "CLOSED" ? 10 : 1;
  if (source.closedAt && source.closePrice !== null && source.closePrice !== undefined) score += 5;
  if (source.mt5PositionTicket) score += 2;
  if (source.orderId) score += 1;
  if (source.mode !== "PAPER") score += 1;
  if (source.enrichmentStatus?.includes("CONFIRMED")) score += 10;
  if (source.openTimeMsc) score += 2;
  if (source.closeTimeMsc) score += 2;
  return score;
}

export function tradeHistoryExecutionSource(item: TradeHistoryItem): TradeExecutionSource {
  return {
    accountLogin: item.account_login ?? null,
    accountServer: item.account_server ?? null,
    closePrice: item.close_price,
    closedAt: item.closed_at,
    closeTimeMsc: item.close_time_msc ?? null,
    internalSymbol: item.internal_symbol,
    mode: item.mode,
    mt5PositionTicket: item.mt5_position_ticket,
    openPrice: item.open_price,
    openedAt: item.opened_at,
    openTimeMsc: item.open_time_msc ?? null,
    enrichmentStatus: item.enrichment_status ?? null,
    orderId: item.order_id,
    positionId: item.position_id,
    side: item.side,
    status: item.status,
    volume: item.volume
  };
}

export function positionToTradeHistoryItem(position: PositionRead): TradeHistoryItem {
  return {
    id: position.id,
    position_id: position.id,
    order_id: position.order_id,
    account_login: position.account_login,
    account_server: position.account_server,
    opened_at: position.opened_at,
    closed_at: position.closed_at,
    open_time_msc: position.open_time_msc ?? null,
    close_time_msc: position.close_time_msc ?? null,
    enrichment_status: position.enrichment_status ?? undefined,
    internal_symbol: position.internal_symbol,
    broker_symbol: position.broker_symbol,
    side: position.side,
    volume: position.volume,
    open_price: position.open_price,
    close_price: position.close_price,
    tp: position.tp,
    profit: position.profit,
    swap: position.swap,
    commission: position.commission,
    fee: position.fee ?? null,
    net_profit: position.net_profit ?? null,
    mode: position.mode,
    mt5_position_ticket: position.mt5_position_ticket,
    closing_deal_ticket: position.closing_deal_ticket,
    status: position.status
  };
}

export function positionExecutionSource(position: PositionRead): TradeExecutionSource {
  return {
    accountLogin: position.account_login ?? null,
    accountServer: position.account_server ?? null,
    closePrice: position.close_price,
    closedAt: position.closed_at,
    closeTimeMsc: position.close_time_msc ?? null,
    internalSymbol: position.internal_symbol,
    mode: position.mode,
    mt5PositionTicket: position.mt5_position_ticket,
    openPrice: position.open_price,
    openedAt: position.opened_at,
    openTimeMsc: position.open_time_msc ?? null,
    enrichmentStatus: position.enrichment_status ?? null,
    orderId: position.order_id,
    positionId: position.id,
    side: position.side,
    status: position.status,
    volume: position.volume
  };
}

export function deduplicateTradeExecutionSources(candidates: TradeExecutionSource[]): TradeExecutionSource[] {
  const seen = new Set<string>();
  const accepted: TradeExecutionSource[] = [];
  const sorted = [...candidates].sort((left, right) => tradeExecutionSourceScore(right) - tradeExecutionSourceScore(left));
  for (const source of sorted) {
    const aliases = tradeExecutionSourceAliases(source);
    if (aliases.some((alias) => seen.has(alias))) continue;
    accepted.push(source);
    aliases.forEach((alias) => seen.add(alias));
  }
  return accepted;
}

export function buildTradeExecutionMarkers(
  positions: PositionRead[],
  history: TradeHistoryItem[],
  symbol: string,
  timeframe: Timeframe,
  settings: TradeExecutionMarkerSettings
): TradeExecutionMarker[] {
  if (!settings.show_trade_execution_markers) {
    return [];
  }

  if (settings.trade_execution_markers_only_m5 && timeframe !== "M5") {
    return [];
  }

  const candidates: TradeExecutionSource[] = [];
  for (const item of history) {
    if (item.internal_symbol === symbol && Number.isFinite(item.open_price)) {
      candidates.push(tradeHistoryExecutionSource(item));
    }
  }
  for (const position of positions) {
    if (position.internal_symbol === symbol && Number.isFinite(position.open_price)) {
      candidates.push(positionExecutionSource(position));
    }
  }

  return deduplicateTradeExecutionSources(candidates)
    .filter((source) => Number.isFinite(source.openPrice))
    .map((source) => {
      const entryTime = Math.floor((source.openTimeMsc ?? new Date(source.openedAt).getTime()) / 1000) as Time;
      const exitTime = source.closeTimeMsc
        ? Math.floor(source.closeTimeMsc / 1000) as Time
        : source.closedAt ? Math.floor(new Date(source.closedAt).getTime() / 1000) as Time : null;
      return {
        id: `${tradeExecutionSourceId(source)}:trade-line`,
        positionId: source.positionId,
        entryTime,
        entryPrice: source.openPrice,
        exitTime,
        exitPrice: source.closePrice,
        side: source.side
      } satisfies TradeExecutionMarker;
    })
    .sort((left, right) => Number(left.entryTime) - Number(right.entryTime))
    .slice(-300);
}

export interface PositionValuation {
  closePrice: number | null;
  profit: number;
  estimated: boolean;
}

export function symbolMappingFor(symbolMappings: SymbolMapping[], symbol: string): SymbolMapping | undefined {
  return symbolMappings.find((item) => item.internal_symbol === symbol);
}

export function contractSizeFor(symbolMappings: SymbolMapping[], symbol: string): number {
  const mapping = symbolMappingFor(symbolMappings, symbol);
  return mapping && Number.isFinite(mapping.contract_size) && mapping.contract_size > 0 ? mapping.contract_size : 1;
}

export function profitConversionRateFor(symbolMappings: SymbolMapping[], symbol: string): number {
  const rate = symbolMappingFor(symbolMappings, symbol)?.risk_conversion_rate;
  return typeof rate === "number" && Number.isFinite(rate) && rate > 0 ? rate : 1;
}

export function positionClosePrice(position: PositionRead, bidPrice: number | null, askPrice: number | null): number | null {
  if (position.side === "BUY") {
    return bidPrice ?? position.current_price ?? null;
  }

  return askPrice ?? position.current_price ?? null;
}

export function calculatePriceDistanceProfit(
  position: PositionRead,
  closePrice: number | null,
  contractSize: number,
  conversionRate = 1,
  anchorToOfficial = false
): number {
  if (closePrice === null || !Number.isFinite(closePrice)) {
    return position.profit ?? 0;
  }

  const direction = position.side === "BUY" ? 1 : -1;
  if (
    anchorToOfficial &&
    typeof position.profit === "number" && Number.isFinite(position.profit) &&
    typeof position.current_price === "number" && Number.isFinite(position.current_price)
  ) {
    const liveDelta = (closePrice - position.current_price) * position.volume * contractSize * conversionRate * direction;
    return position.profit + liveDelta;
  }
  return (closePrice - position.open_price) * position.volume * contractSize * conversionRate * direction;
}

export function hasLiveClosePrice(position: PositionRead, bidPrice: number | null, askPrice: number | null, liveTickFresh: boolean): boolean {
  return liveTickFresh && (position.side === "BUY" ? bidPrice !== null : askPrice !== null);
}

export function calculatePositionProfit(
  position: PositionRead,
  closePrice: number | null,
  contractSize: number,
  useLiveEstimate = false,
  conversionRate = 1
): number {
  if (useLiveEstimate) {
    return calculatePriceDistanceProfit(position, closePrice, contractSize, conversionRate, true);
  }

  if (position.mt5_position_ticket && typeof position.profit === "number" && Number.isFinite(position.profit)) {
    return position.profit;
  }

  return calculatePriceDistanceProfit(position, closePrice, contractSize, conversionRate);
}

export function positionValuation(
  position: PositionRead,
  symbolMappings: SymbolMapping[],
  bidPrice: number | null,
  askPrice: number | null,
  liveTickFresh = false
): PositionValuation {
  const closePrice = positionClosePrice(position, bidPrice, askPrice);
  const estimated = position.mode !== "PAPER" && hasLiveClosePrice(position, bidPrice, askPrice, liveTickFresh);
  const profit = calculatePositionProfit(
    position,
    closePrice,
    contractSizeFor(symbolMappings, position.internal_symbol),
    estimated,
    profitConversionRateFor(symbolMappings, position.internal_symbol)
  );
  return { closePrice, profit, estimated };
}

export function tradeLinesForSymbol(
  positions: PositionRead[],
  symbol: string,
  symbolMappings: SymbolMapping[],
  bidPrice: number | null,
  askPrice: number | null,
  liveTickFresh: boolean,
  accountCurrency: string,
  selectedPositionId: number | null
): TradeLine[] {
  return positions
    .filter((position) => position.internal_symbol === symbol)
    .filter(isReallyOpenPosition)
    .flatMap((position) => {
      const contractSize = contractSizeFor(symbolMappings, position.internal_symbol);
      const valuation = positionValuation(position, symbolMappings, bidPrice, askPrice, liveTickFresh);
      const selected = selectedPositionId === position.id;
      const entryProfit = valuation.profit;
      const profitPrefix = valuation.estimated ? "≈" : "";

      const lines: TradeLine[] = [
        {
          id: `entry-${position.id}`,
          positionId: position.id,
          price: position.open_price,
          label: `${position.side} ${position.volume.toFixed(2)}, ${profitPrefix}${entryProfit.toFixed(2)} ${accountCurrency}`,
          tone: "entry",
          side: position.side,
          volume: position.volume,
          openPrice: position.open_price,
          profit: entryProfit,
          profitEstimated: valuation.estimated,
          contractSize,
          currency: accountCurrency,
          selected
        }
      ];

      if (position.tp) {
        const direction = position.side === "SELL" ? -1 : 1;

        const tpPercent =
          position.tp_percent ??
          ((position.tp - position.open_price) / position.open_price) * 100 * direction;

        // TP es una estimación futura, por tanto sí se calcula.
        const tpProfit = calculatePriceDistanceProfit(
          position,
          position.tp,
          contractSize,
          profitConversionRateFor(symbolMappings, position.internal_symbol)
        );

        lines.push({
          id: `tp-${position.id}`,
          positionId: position.id,
          price: position.tp,
          label: `TP, ${tpProfit >= 0 ? "+" : ""}${tpProfit.toFixed(2)} ${accountCurrency}, ${tpPercent.toFixed(2)}%`,
          tone: "tp",
          side: position.side,
          volume: position.volume,
          openPrice: position.open_price,
          profit: tpProfit,
          contractSize,
          currency: accountCurrency,
          editable: selected,
          muted: !selected
        });
      }

      return lines;
    });
}

export function historyGrossProfit(item: TradeHistoryItem, symbolMappings: SymbolMapping[]): number {
  if (typeof item.net_profit === "number" && Number.isFinite(item.net_profit)) {
    return item.net_profit;
  }
  if (typeof item.profit === "number" && Number.isFinite(item.profit)) {
    return item.profit + (item.swap ?? 0) + (item.commission ?? 0) + (item.fee ?? 0);
  }

  if (item.mode !== "PAPER") {
    return 0;
  }

  if (item.close_price === null || item.close_price === undefined) {
    return 0;
  }

  const direction = item.side === "BUY" ? 1 : -1;
  return (item.close_price - item.open_price) * item.volume * contractSizeFor(symbolMappings, item.internal_symbol)
    * profitConversionRateFor(symbolMappings, item.internal_symbol) * direction;
}

