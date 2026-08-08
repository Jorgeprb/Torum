import type { ReactNode } from "react";

import type { Timeframe } from "../../services/market";
import type { IndicatorLineOutput } from "../../services/indicators";
import type { MobileView } from "../mobile/AccountDrawer";
import { IndicatorsPanel } from "../indicators/IndicatorsPanel";
import { NewsProviderPage } from "../news/NewsProviderPage";
import { StrategyPerformancePage } from "../performance/StrategyPerformancePage";
import { TradingSettingsPage } from "../settings/TradingSettingsPage";
import { StrategyPanel } from "../strategies/StrategyPanel";
import { StrategySimulatorPage } from "../strategies/simulator/StrategySimulatorPage";

interface TradingWorkspacePanelsProps {
  activeView: MobileView;
  chartSymbols: string[];
  timeframes: Timeframe[];
  indicatorLines: IndicatorLineOutput[];
  symbol: string;
  timeframe: Timeframe;
  history: ReactNode;
  diagnostics: ReactNode;
  onChartContextChanged: () => void;
  onStrategyChanged: () => void;
}

export function TradingWorkspacePanels({
  activeView,
  chartSymbols,
  timeframes,
  indicatorLines,
  symbol,
  timeframe,
  history,
  diagnostics,
  onChartContextChanged,
  onStrategyChanged,
}: TradingWorkspacePanelsProps) {
  return (
    <div className="mobile-view-panel">
      {activeView === "strategies" ? <StrategyPanel symbols={chartSymbols} timeframes={timeframes} onChanged={onStrategyChanged} /> : null}
      {activeView === "simulator" ? <StrategySimulatorPage /> : null}
      {activeView === "performance" ? <StrategyPerformancePage /> : null}
      {activeView === "indicators" ? <IndicatorsPanel indicatorLines={indicatorLines} onChanged={onChartContextChanged} symbol={symbol} timeframe={timeframe} /> : null}
      {activeView === "settings" ? <><TradingSettingsPage onChanged={onStrategyChanged} />{diagnostics}</> : null}
      {activeView === "history" ? history : null}
      {activeView === "news" ? <NewsProviderPage onChanged={onChartContextChanged} /> : null}
    </div>
  );
}
