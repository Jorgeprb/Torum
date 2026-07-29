import { Activity, BadgeEuro, Clock3, Gauge, Percent, ShieldAlert, Target, TrendingDown, Trophy } from "lucide-react";

import type { TorumV1BacktestMetrics } from "../../../services/strategies";

function money(value: number): string {
  return new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

export function StrategySimulationMetrics({ metrics }: { metrics: TorumV1BacktestMetrics }) {
  const cards = [
    { label: "Resultado neto", value: `${money(metrics.net_profit)} · ${metrics.total_return_pct.toFixed(2)}%`, icon: BadgeEuro, tone: metrics.net_profit >= 0 ? "positive" : "negative" },
    { label: "Operaciones", value: String(metrics.closed_trades), icon: Activity, tone: "neutral" },
    { label: "Acierto", value: `${metrics.win_rate_pct.toFixed(1)}%`, icon: Target, tone: metrics.win_rate_pct >= 50 ? "positive" : "neutral" },
    { label: "Profit factor", value: metrics.profit_factor == null ? "—" : metrics.profit_factor.toFixed(2), icon: Trophy, tone: (metrics.profit_factor ?? 0) >= 1 ? "positive" : "negative" },
    { label: "Drawdown máximo", value: `${money(metrics.max_drawdown)} · ${metrics.max_drawdown_pct.toFixed(2)}%`, icon: TrendingDown, tone: "negative" },
    { label: "Expectativa", value: money(metrics.expectancy), icon: Gauge, tone: metrics.expectancy >= 0 ? "positive" : "negative" },
    { label: "Exposición", value: `${metrics.exposure_pct.toFixed(1)}%`, icon: Percent, tone: "neutral" },
    { label: "Duración media", value: `${metrics.average_bars_held.toFixed(1)} velas`, icon: Clock3, tone: "neutral" },
    { label: "Señales bloqueadas", value: String(metrics.blocked_signals), icon: ShieldAlert, tone: metrics.blocked_signals > 0 ? "warning" : "neutral" },
  ];

  return (
    <>
      <div className="strategy-sim-metric-grid">
        {cards.map((card) => {
          const Icon = card.icon;
          return (
            <article className={`strategy-sim-metric strategy-sim-metric--${card.tone}`} key={card.label}>
              <Icon size={17} />
              <span>{card.label}</span>
              <strong>{card.value}</strong>
            </article>
          );
        })}
      </div>
      <div className="strategy-sim-stat-table">
        <div><span>Balance inicial</span><strong>{money(metrics.initial_balance)}</strong></div>
        <div><span>Comisiones</span><strong>{money(metrics.total_commission)}</strong></div>
        <div><span>Balance final</span><strong>{money(metrics.final_balance)}</strong></div>
        <div><span>Equity final</span><strong>{money(metrics.final_equity)}</strong></div>
        <div><span>Ganadoras / perdedoras</span><strong>{metrics.winning_trades} / {metrics.losing_trades}</strong></div>
        <div><span>Ganancia media</span><strong>{money(metrics.average_win)}</strong></div>
        <div><span>Payoff / recuperación</span><strong>{metrics.payoff_ratio?.toFixed(2) ?? "—"} / {metrics.recovery_factor?.toFixed(2) ?? "—"}</strong></div>
        <div><span>Pérdida media</span><strong>{money(metrics.average_loss)}</strong></div>
        <div><span>Mejor / peor</span><strong>{money(metrics.best_trade)} / {money(metrics.worst_trade)}</strong></div>
        <div><span>MFE / MAE medios</span><strong>{metrics.average_mfe_pct.toFixed(2)}% / {metrics.average_mae_pct.toFixed(2)}%</strong></div>
        <div><span>Pullback medio</span><strong>{metrics.average_pullback_pct.toFixed(2)}%</strong></div>
        <div><span>Riesgo medio entrada</span><strong>{money(metrics.average_risk_at_entry)}</strong></div>
        <div><span>Máx. simultáneas</span><strong>{metrics.max_concurrent_trades}</strong></div>
        <div><span>Días / ops. por día</span><strong>{metrics.trading_days} / {metrics.trades_per_day.toFixed(2)}</strong></div>
        <div><span>Racha máx. G / P</span><strong>{metrics.max_consecutive_wins} / {metrics.max_consecutive_losses}</strong></div>
        <div><span>Setups detectados</span><strong>{metrics.signals_detected}</strong></div>
      </div>
    </>
  );
}
