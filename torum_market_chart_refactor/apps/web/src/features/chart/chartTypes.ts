import type { Time } from "lightweight-charts";
import type { Candle } from "../../services/market";
import type { PriceAlertRead } from "../../services/alerts";
import type { NoTradeZone } from "../../services/news";
import type { IndicatorLineOutput, StrategyPullbackDebug } from "../../services/indicators";
import type {
  ChartDrawingCreate,
  ChartDrawingRead,
  ChartDrawingUpdate,
  DrawingTool,
} from "../../services/drawings";

export interface MarketChartProps {
  candles: Candle[];
  loadingCandles?: boolean;
  symbolResetToken?: number;
  hardResetToken?: number;
  noTradeZones?: NoTradeZone[];
  indicatorLines?: IndicatorLineOutput[];
  strategyDebugPullbacks?: StrategyPullbackDebug[];
  drawings?: ChartDrawingRead[];
  drawingTool?: DrawingTool;
  selectedDrawingId?: string | null;
  symbol: string;
  timeframe: string;
  onCreateDrawing?: (drawing: ChartDrawingCreate) => void;
  onUpdateDrawing?: (drawing: ChartDrawingRead, patch: ChartDrawingUpdate) => void | Promise<void>;
  onDeleteDrawing?: (drawingId: string) => void;
  onSelectDrawing?: (drawingId: string | null) => void;
  tradeLines?: TradeLine[];
  tradeMarkers?: TradeMarker[];
  onSelectPosition?: (positionId: number) => void;
  onUpdatePositionTp?: (positionId: number, tp: number, closePrice?: number | null) => void | Promise<void>;
  alertToolActive?: boolean;
  priceAlerts?: PriceAlertRead[];
  onCreatePriceAlert?: (price: number) => void;
  onUpdatePriceAlert?: (alert: PriceAlertRead, targetPrice: number) => void;
  onCancelPriceAlert?: (alertId: string) => void;
  bidPrice?: number | null;
  askPrice?: number | null;
  showBidLine?: boolean;
  showAskLine?: boolean;
  autoFollowEnabled?: boolean;
  onAutoFollowChange?: (enabled: boolean) => void;
  recenterToken?: number;
  resetKey?: string;
  showFutureNewsZones?: boolean;
  autoExtendToFutureNews?: boolean;
}

export interface ZoneOverlay {
  id: number;
  left: number;
  width: number;
  zone: NoTradeZone;
}

export interface TradeLine {
  id: string;
  positionId?: number;
  price: number;
  label: string;
  tone: "entry" | "tp" | "close";
  side?: "BUY" | "SELL";
  volume?: number;
  openPrice?: number;
  profit?: number;
  contractSize?: number;
  currency?: string;
  editable?: boolean;
  muted?: boolean;
  selected?: boolean;
}

export interface TradeMarker {
  id: string;
  time: Time;
  price: number;
  kind: "BUY" | "CLOSE";
  label: string;
}

export type ChartLineStyle = "solid" | "dashed";

export interface PriceAlertVisualStyle {
  color: string;
  lineStyle: ChartLineStyle;
}

export interface TradeLineOverlay extends TradeLine {
  y: number;
}

export interface TradeMarkerOverlay extends TradeMarker {
  x: number;
  y: number;
}

export interface PriceAlertOverlay {
  alert: PriceAlertRead;
  y: number;
  targetPrice: number;
}

export interface PullbackDebugOverlay {
  debug: StrategyPullbackDebug;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}
