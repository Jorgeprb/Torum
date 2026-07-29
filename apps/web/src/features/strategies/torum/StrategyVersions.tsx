import { History, RotateCcw } from "lucide-react";
import type { StrategyConfigVersion } from "../../../services/strategies";

interface StrategyVersionsProps {
  versions: StrategyConfigVersion[];
  onRestore: (revision: number) => void;
  restoring: number | null;
}

export function StrategyVersions({ versions, onRestore, restoring }: StrategyVersionsProps) {
  return (
    <section className="strategy-version-panel">
      <div className="settings-card__title"><History size={18} /> Versiones</div>
      {versions.length === 0 ? <p className="notice-strip">Todavía no hay versiones guardadas.</p> : null}
      <div className="strategy-version-list">
        {versions.map((version) => (
          <article key={version.id}>
            <div>
              <strong>Revisión {version.revision}</strong>
              <small>{new Date(version.created_at).toLocaleString()} · {version.change_note ?? "Sin nota"}</small>
            </div>
            <button disabled={restoring === version.revision} type="button" onClick={() => onRestore(version.revision)}>
              <RotateCcw size={15} /> Restaurar
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}
