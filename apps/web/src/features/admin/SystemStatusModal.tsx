import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, Power, RefreshCw, ServerCrash, X } from "lucide-react";

import {
  type RestartTarget,
  type SystemHealthStatus,
  type SystemRestartAction,
  type SystemStatusResponse,
  getAdminSystemStatus,
  restartSystemTarget
} from "../../services/adminSystem";

interface SystemStatusModalProps {
  open: boolean;
  onClose: () => void;
}

const restartTargets: Array<{ target: RestartTarget; label: string; danger?: boolean }> = [
  { target: "mt5", label: "Reiniciar MT5" },
  { target: "api", label: "Reiniciar API" },
  { target: "bridge", label: "Reiniciar bridge" },
  { target: "frontend", label: "Reiniciar frontend" },
  { target: "all", label: "Reiniciar todo", danger: true },
  { target: "pc", label: "Reiniciar PC", danger: true }
];

function statusIcon(status: SystemHealthStatus) {
  if (status === "OK") {
    return <CheckCircle2 size={18} />;
  }
  if (status === "FAIL") {
    return <ServerCrash size={18} />;
  }
  if (status === "RESTARTING") {
    return <Loader2 className="spin" size={18} />;
  }
  return <AlertTriangle size={18} />;
}

function statusClass(status: SystemHealthStatus) {
  return `system-status-card system-status-card--${status.toLowerCase()}`;
}

function confirmationText(target: RestartTarget) {
  return target === "pc" ? "REINICIAR PC" : "REINICIAR";
}

export function SystemStatusModal({ open, onClose }: SystemStatusModalProps) {
  const [status, setStatus] = useState<SystemStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingTarget, setPendingTarget] = useState<RestartTarget | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [action, setAction] = useState<SystemRestartAction | null>(null);

  const expectedConfirmation = useMemo(() => (pendingTarget ? confirmationText(pendingTarget) : ""), [pendingTarget]);

  async function refreshStatus() {
    setLoading(true);
    setError(null);
    try {
      setStatus(await getAdminSystemStatus());
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo leer estado");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!open) {
      return;
    }
    void refreshStatus();
    const intervalId = window.setInterval(() => void refreshStatus(), 7000);
    return () => window.clearInterval(intervalId);
  }, [open]);

  async function confirmRestart() {
    if (!pendingTarget || confirmation.trim().toUpperCase() !== expectedConfirmation) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await restartSystemTarget(pendingTarget, confirmation.trim().toUpperCase());
      setAction(response);
      setPendingTarget(null);
      setConfirmation("");
      void refreshStatus();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo reiniciar");
    } finally {
      setLoading(false);
    }
  }

  if (!open) {
    return null;
  }

  return (
    <div className="modal-backdrop system-modal-backdrop" role="presentation">
      <div className="confirm-modal system-status-modal" role="dialog" aria-modal="true" aria-label="Estado del sistema">
        <div className="system-status-modal__head">
          <div>
            <p className="eyebrow">Admin</p>
            <h2>Estado del sistema</h2>
          </div>
          <button aria-label="Cerrar" className="mobile-icon-button" type="button" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className={status ? `system-status-summary system-status-summary--${status.status.toLowerCase()}` : "system-status-summary"}>
          <Power size={18} />
          <strong>{status?.message ?? "Leyendo estado"}</strong>
          <span>{status?.account_mode ?? "UNKNOWN"}</span>
          <button className="toolbar-action" disabled={loading} type="button" onClick={() => void refreshStatus()}>
            {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            Refrescar
          </button>
        </div>

        {error ? <div className="compact-error">{error}</div> : null}

        <div className="system-status-grid">
          {status?.items.map((item) => (
            <article className={statusClass(item.status)} key={item.key}>
              <div>
                {statusIcon(item.status)}
                <strong>{item.label}</strong>
                <span>{item.status}</span>
              </div>
              <p>{item.message}</p>
            </article>
          )) ?? <div className="compact-warning">Cargando...</div>}
        </div>

        <div className="system-restart-grid">
          {restartTargets.map((target) => (
            <button
              className={target.danger ? "system-restart-button system-restart-button--danger" : "system-restart-button"}
              disabled={loading || status?.action_running}
              key={target.target}
              type="button"
              onClick={() => {
                setPendingTarget(target.target);
                setConfirmation("");
              }}
            >
              {target.label}
            </button>
          ))}
        </div>

        {pendingTarget ? (
          <div className="system-confirm-box">
            <label>
              Escribe {expectedConfirmation}
              <input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
            </label>
            <div className="modal-actions">
              <button className="toolbar-action" type="button" onClick={() => setPendingTarget(null)}>
                Cancelar
              </button>
              <button
                className="primary-button"
                disabled={confirmation.trim().toUpperCase() !== expectedConfirmation || loading}
                type="button"
                onClick={() => void confirmRestart()}
              >
                Confirmar
              </button>
            </div>
            {pendingTarget === "pc" ? <p>Reiniciar PC corta conexion.</p> : null}
          </div>
        ) : null}

        {action ? (
          <pre className="system-log-tail">
            {action.target}: {action.status}
            {"\n"}
            {action.log_tail}
          </pre>
        ) : null}
      </div>
    </div>
  );
}
