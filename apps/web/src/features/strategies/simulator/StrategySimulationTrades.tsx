import { Crosshair, Download, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { TorumV1BacktestTrade } from "../../../services/strategies";

interface StrategySimulationTradesProps {
  trades: TorumV1BacktestTrade[];
  onFocus: (trade: TorumV1BacktestTrade) => void;
  onExport: () => void;
}

function money(value: number): string {
  return new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

export function StrategySimulationTrades({ trades, onFocus, onExport }: StrategySimulationTradesProps) {
  const [query, setQuery] = useState("");
  const [outcome, setOutcome] = useState<"ALL" | "WIN" | "LOSS" | "OPEN">("ALL");
  const [visibleCount, setVisibleCount] = useState(300);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return trades.filter((trade) => {
      if (outcome === "WIN" && trade.net_profit <= 0) return false;
      if (outcome === "LOSS" && trade.net_profit >= 0) return false;
      if (outcome === "OPEN" && trade.status !== "OPEN") return false;
      if (!needle) return true;
      return `${trade.id} ${trade.support_level ?? ""} ${trade.operation_zone_id ?? ""} ${trade.exit_reason ?? ""}`.toLowerCase().includes(needle);
    });
  }, [outcome, query, trades]);
  const visible = useMemo(() => filtered.slice(0, visibleCount), [filtered, visibleCount]);
  useEffect(() => setVisibleCount(300), [outcome, query, trades]);

  return (
    <section className="strategy-sim-table-card">
      <header className="strategy-sim-section-header">
        <div>
          <strong>Operaciones simuladas</strong>
          <span>{filtered.length} de {trades.length}</span>
        </div>
        <button className="toolbar-action" type="button" onClick={onExport}><Download size={15} /> CSV</button>
      </header>
      <div className="strategy-sim-table-tools">
        <label><Search size={15} /><input placeholder="Buscar operación…" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <select value={outcome} onChange={(event) => setOutcome(event.target.value as typeof outcome)}>
          <option value="ALL">Todas</option>
          <option value="WIN">Ganadoras</option>
          <option value="LOSS">Perdedoras</option>
          <option value="OPEN">Abiertas</option>
        </select>
      </div>
      <div className="strategy-sim-table-scroll">
        <table className="strategy-sim-table">
          <thead>
            <tr>
              <th>ID</th><th>Entrada</th><th>Salida</th><th>Vol.</th><th>PB</th><th>Soporte</th><th>Resultado</th><th>MFE / MAE</th><th />
            </tr>
          </thead>
          <tbody>
            {visible.map((trade) => (
              <tr key={trade.id}>
                <td><strong>{trade.id}</strong><small>{trade.ath_zone ?? "sin ATH"}</small></td>
                <td>{new Date(trade.entry_time).toLocaleString()}<small>{trade.entry_price.toFixed(3)}</small></td>
                <td>{trade.exit_time ? new Date(trade.exit_time).toLocaleString() : "Abierta"}<small>{trade.exit_price?.toFixed(3) ?? `TP ${trade.tp_price.toFixed(3)}`}</small></td>
                <td>{trade.volume.toFixed(2)}<small>x{trade.multiplier}</small></td>
                <td>{trade.pullback_pct?.toFixed(2) ?? "—"}%</td>
                <td>{trade.support_level ? `S${trade.support_level}` : "—"}</td>
                <td className={trade.net_profit >= 0 ? "profit-positive" : "profit-negative"}><strong>{money(trade.net_profit)}</strong><small>{trade.return_pct.toFixed(3)}%</small></td>
                <td>{trade.mfe_pct.toFixed(2)}%<small>{trade.mae_pct.toFixed(2)}%</small></td>
                <td><button aria-label={`Centrar ${trade.id}`} className="strategy-sim-focus-button" title="Centrar en gráfico" type="button" onClick={() => onFocus(trade)}><Crosshair size={16} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {visible.length < filtered.length ? <button className="strategy-sim-load-more" type="button" onClick={() => setVisibleCount((current) => current + 300)}>Mostrar 300 más · {filtered.length - visible.length} pendientes</button> : null}
      </div>
    </section>
  );
}
