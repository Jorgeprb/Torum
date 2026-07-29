import {
  AlertTriangle,
  CheckCircle2,
  CircleDollarSign,
  Database,
  FlaskConical,
  Layers3,
  Play,
  RotateCcw,
  Settings2,
  ShieldCheck,
  Square,
} from "lucide-react";

import type {
  SimulatorPreset,
  SimulatorRequestSettings,
  SimulatorSetupStep,
  SimulatorSymbol,
  SimulatorValidationIssue,
} from "./simulatorTypes";

interface StrategySimulatorLaunchCardProps {
  configurationRevision: number | null;
  fromLocal: string;
  issueCount: number;
  issues: SimulatorValidationIssue[];
  onCancel: () => void;
  onEditStep: (step: SimulatorSetupStep) => void;
  onReset: () => void;
  onRun: () => void;
  overrideCount: number;
  preset: SimulatorPreset;
  request: SimulatorRequestSettings;
  running: boolean;
  selectedSupportCount: number;
  selectedZoneCount: number;
  symbol: SimulatorSymbol;
  toLocal: string;
}

const presetLabels: Record<SimulatorPreset, string> = {
  REALISTIC: "Realista",
  CONSERVATIVE: "Conservador",
  TECHNICAL: "Solo técnico",
  CUSTOM: "Personalizado",
};

function formatRange(fromLocal: string, toLocal: string, candleLimit: number): string {
  if (!fromLocal && !toLocal) return `Últimas ${candleLimit.toLocaleString("es-ES")} velas M5`;
  if (fromLocal && toLocal) return `${new Date(fromLocal).toLocaleString("es-ES")} → ${new Date(toLocal).toLocaleString("es-ES")}`;
  if (fromLocal) return `Desde ${new Date(fromLocal).toLocaleString("es-ES")}`;
  return `Hasta ${new Date(toLocal).toLocaleString("es-ES")}`;
}

export function StrategySimulatorLaunchCard({
  configurationRevision,
  fromLocal,
  issueCount,
  issues,
  onCancel,
  onEditStep,
  onReset,
  onRun,
  overrideCount,
  preset,
  request,
  running,
  selectedSupportCount,
  selectedZoneCount,
  symbol,
  toLocal,
}: StrategySimulatorLaunchCardProps) {
  const errors = issues.filter((issue) => issue.severity === "ERROR");
  const warnings = issues.filter((issue) => issue.severity === "WARNING");
  const canRun = errors.length === 0 && !running;

  return (
    <section className="strategy-sim-launch-card" aria-label="Resumen y lanzamiento de la simulación">
      <header>
        <div className="strategy-sim-launch-card__icon"><FlaskConical size={22} /></div>
        <div>
          <p className="eyebrow">Escenario listo para probar</p>
          <h3>{symbol} · Torum V1</h3>
        </div>
        <span className={errors.length ? "strategy-sim-ready-badge is-error" : warnings.length ? "strategy-sim-ready-badge is-warning" : "strategy-sim-ready-badge is-ready"}>
          {errors.length ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
          {errors.length ? `${errors.length} error${errors.length === 1 ? "" : "es"}` : warnings.length ? `${warnings.length} aviso${warnings.length === 1 ? "" : "s"}` : "Preparado"}
        </span>
      </header>

      <div className="strategy-sim-launch-summary">
        <button type="button" onClick={() => onEditStep("MARKET")}>
          <Database size={16} />
          <span><small>Datos</small><strong>{formatRange(fromLocal, toLocal, request.candle_limit)}</strong></span>
        </button>
        <button type="button" onClick={() => onEditStep("FILTERS")}>
          <Layers3 size={16} />
          <span><small>Zonas y soportes</small><strong>{request.use_operation_zones ? selectedZoneCount : 0} regiones · {request.use_supports ? selectedSupportCount : 0} soportes</strong></span>
        </button>
        <button type="button" onClick={() => onEditStep("PARAMETERS")}>
          <Settings2 size={16} />
          <span><small>Configuración</small><strong>{presetLabels[preset]} · {overrideCount} cambios temporales</strong></span>
        </button>
        <button type="button" onClick={() => onEditStep("EXECUTION")}>
          <CircleDollarSign size={16} />
          <span><small>Ejecución</small><strong>{request.entry_model === "NEXT_OPEN" ? "Siguiente apertura" : "Cierre de confirmación"}</strong></span>
        </button>
      </div>

      {issues.length ? (
        <div className="strategy-sim-launch-issues">
          {issues.slice(0, 3).map((issue) => (
            <button className={`is-${issue.severity.toLowerCase()}`} key={issue.id} type="button" onClick={() => issue.step && onEditStep(issue.step)}>
              {issue.severity === "ERROR" ? <AlertTriangle size={15} /> : issue.severity === "WARNING" ? <AlertTriangle size={15} /> : <ShieldCheck size={15} />}
              <span><strong>{issue.title}</strong><small>{issue.detail}</small></span>
            </button>
          ))}
          {issueCount > 3 ? <small className="strategy-sim-launch-issues__more">Hay {issueCount - 3} avisos adicionales en la configuración.</small> : null}
        </div>
      ) : (
        <div className="strategy-sim-safety-note"><ShieldCheck size={16} /> La prueba es aislada: no publica parámetros ni envía órdenes a MetaTrader.</div>
      )}

      <div className="strategy-sim-launch-meta">
        <span>Balance inicial <strong>{request.initial_balance.toLocaleString("es-ES", { maximumFractionDigits: 2 })}</strong></span>
        <span>Revisión publicada <strong>{configurationRevision ?? "—"}</strong></span>
        <span>Traza <strong>{request.debug_level}</strong></span>
      </div>

      <footer>
        <button className="toolbar-action" disabled={running} type="button" onClick={onReset}><RotateCcw size={16} /> Restaurar escenario</button>
        {running ? (
          <button className="danger-button strategy-sim-launch-primary" type="button" onClick={onCancel}><Square size={16} /> Cancelar simulación</button>
        ) : (
          <button className="primary-button strategy-sim-launch-primary" disabled={!canRun} type="button" onClick={onRun}><Play size={18} /> Ejecutar simulación</button>
        )}
      </footer>
    </section>
  );
}
