import { BarChart3 } from "lucide-react";
import type { TorumV1Replay } from "../../../services/strategies";

export function StrategyReplay({ replay }: { replay: TorumV1Replay | null }) {
  if (!replay) {
    return <div className="strategy-empty-state">Ejecuta «Replay 500 velas» para revisar señales técnicas históricas.</div>;
  }
  return (
    <section className="strategy-replay">
      <header>
        <BarChart3 size={18} />
        <div>
          <strong>{replay.signal_count} setups técnicos</strong>
          <span>{replay.candles_analyzed} velas analizadas · sin enviar órdenes</span>
        </div>
      </header>
      {replay.signals.length > 0 ? (
        <ol>
          {replay.signals.slice(-12).reverse().map((signal) => (
            <li key={`${signal.confirmation_time}:${signal.pullback_low_time ?? "none"}`}>
              <strong>{new Date(signal.confirmation_time).toLocaleString()}</strong>
              <span>
                {signal.pullback_pct != null ? `PB ${signal.pullback_pct.toFixed(2)}%` : "PB"}
                {signal.support_level != null ? ` · S${signal.support_level}` : ""}
                {` · x${signal.desired_multiplier}`}
              </span>
            </li>
          ))}
        </ol>
      ) : <p>No se encontraron setups con la configuración actual.</p>}
      <small>{replay.notes.join(" ")}</small>
    </section>
  );
}
