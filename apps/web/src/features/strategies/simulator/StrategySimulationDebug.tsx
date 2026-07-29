import { Bug, Crosshair, Filter, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { TorumV1Backtest, TorumV1BacktestDebugEvent } from "../../../services/strategies";

interface StrategySimulationDebugProps {
  result: TorumV1Backtest;
  onFocusEvent?: (event: TorumV1BacktestDebugEvent) => void;
}

export function StrategySimulationDebug({ result, onFocusEvent }: StrategySimulationDebugProps) {
  const [stage, setStage] = useState("ALL");
  const [status, setStatus] = useState("ALL");
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(300);
  const stages = useMemo(() => Array.from(new Set(result.debug_events.map((item) => item.stage))).sort(), [result.debug_events]);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return result.debug_events.filter((event) => {
      if (stage !== "ALL" && event.stage !== stage) return false;
      if (status !== "ALL" && event.status !== status) return false;
      if (!needle) return true;
      return `${event.reason_code} ${event.summary} ${JSON.stringify(event.details)}`.toLowerCase().includes(needle);
    });
  }, [query, result.debug_events, stage, status]);
  const visible = useMemo(() => filtered.slice().reverse().slice(0, visibleCount), [filtered, visibleCount]);

  useEffect(() => setVisibleCount(300), [query, stage, status, result.generated_at]);

  return (
    <section className="strategy-sim-debug-card">
      <header className="strategy-sim-section-header">
        <div><Bug size={18} /><strong>Depuración detallada</strong><span>{filtered.length} eventos</span></div>
      </header>
      <div className="strategy-sim-debug-layout">
        <aside className="strategy-sim-rejection-summary">
          <strong>Motivos de descarte</strong>
          {Object.entries(result.metrics.rejection_counts).slice(0, 30).map(([reason, count]) => (
            <button key={reason} type="button" onClick={() => { setQuery(reason); setStatus("REJECT"); }}>
              <span>{reason.split("_").join(" ")}</span><b>{count}</b>
            </button>
          ))}
          {Object.keys(result.metrics.rejection_counts).length === 0 ? <p>Sin descartes registrados.</p> : null}
        </aside>
        <div className="strategy-sim-debug-main">
          <div className="strategy-sim-debug-tools">
            <label><Search size={15} /><input placeholder="Buscar motivo o detalle…" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
            <label><Filter size={15} /><select value={stage} onChange={(event) => setStage(event.target.value)}><option value="ALL">Todas las fases</option>{stages.map((item) => <option value={item} key={item}>{item}</option>)}</select></label>
            <select value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="ALL">Todos los estados</option><option value="ENTRY">Entradas</option><option value="EXIT">Salidas</option><option value="REJECT">Descartes</option><option value="WARN">Avisos</option>
            </select>
          </div>
          <div className="strategy-sim-event-list">
            {visible.map((event, index) => (
              <details className={`strategy-sim-event strategy-sim-event--${event.status.toLowerCase()}`} key={`${event.time}:${event.candle_index}:${event.reason_code}:${index}`}>
                <summary>
                  <time>{new Date(event.time).toLocaleString()}</time>
                  <span>{event.stage}</span>
                  <strong>{event.summary}</strong>
                  <code>{event.reason_code}</code>
                  {onFocusEvent && event.price != null ? (
                    <button aria-label="Centrar evento en el gráfico" className="strategy-sim-focus-button" title="Ver en gráfico" type="button" onClick={(click) => { click.preventDefault(); click.stopPropagation(); onFocusEvent(event); }}><Crosshair size={15} /></button>
                  ) : null}
                </summary>
                <pre>{JSON.stringify(event.details, null, 2)}</pre>
              </details>
            ))}
            {filtered.length === 0 ? <div className="strategy-empty-state">No hay eventos para estos filtros.</div> : null}
            {visible.length < filtered.length ? <button className="strategy-sim-load-more" type="button" onClick={() => setVisibleCount((current) => current + 300)}>Mostrar 300 más · {filtered.length - visible.length} pendientes</button> : null}
          </div>
        </div>
      </div>
    </section>
  );
}
