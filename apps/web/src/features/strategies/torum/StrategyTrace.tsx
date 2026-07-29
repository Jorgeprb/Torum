import { Check, CircleAlert, CircleDashed, Clock3, Minus } from "lucide-react";
import type { StrategyTraceStep, TorumV1Simulation } from "../../../services/strategies";

const icons = {
  PASS: Check,
  FAIL: CircleAlert,
  WAIT: Clock3,
  WARN: CircleAlert,
  SKIP: Minus,
} as const;

function Step({ step }: { step: StrategyTraceStep }) {
  const Icon = icons[step.status] ?? CircleDashed;
  return (
    <li className={`strategy-trace-step strategy-trace-step--${step.status.toLowerCase()}`}>
      <Icon size={17} />
      <div>
        <strong>{step.label}</strong>
        <span>{step.summary}</span>
      </div>
    </li>
  );
}

export function StrategyTrace({ simulation }: { simulation: TorumV1Simulation | null }) {
  if (!simulation) return <div className="strategy-empty-state">Pulsa «Simular ahora» para ver el flujo real.</div>;
  return (
    <section className="strategy-trace">
      <header className={`strategy-trace__decision strategy-trace__decision--${simulation.decision.toLowerCase()}`}>
        <strong>{simulation.symbol}: {simulation.decision === "BUY" ? "COMPRARÍA" : simulation.decision === "BLOCKED" ? "BLOQUEADO" : "ESPERANDO"}</strong>
        <span>{simulation.summary}</span>
      </header>
      <ol>{simulation.steps.map((step) => <Step key={step.id} step={step} />)}</ol>
    </section>
  );
}
