import { useEffect, useMemo, useRef, useState } from "react";
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

const restartTargets: Array<{ target: RestartTarget; itemKey?: string; label: string; danger?: boolean }> = [
  { target: "mt5", itemKey: "mt5", label: "MT5 terminal" },
  { target: "bridge", itemKey: "bridge", label: "mt5_bridge" },
  { target: "api", itemKey: "api", label: "API/backend" },
  { target: "frontend", itemKey: "frontend", label: "frontend" },
  { target: "all", label: "Todo Torum", danger: true },
  { target: "pc", label: "PC", danger: true }
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

function elapsedLabel(timestamp: number | null, nowMs: number) {
  if (!timestamp) {
    return "Sin refrescar";
  }
  const seconds = Math.max(0, Math.floor((nowMs - timestamp) / 1000));
  if (seconds < 2) {
    return "Refrescado ahora";
  }
  if (seconds < 60) {
    return `Refrescado hace ${seconds}s`;
  }
  return `Refrescado hace ${Math.floor(seconds / 60)}m`;
}

function confirmationText(target: RestartTarget) {
  return target === "pc" ? "REINICIAR PC" : "REINICIAR";
}

export function SystemStatusModal({ open, onClose }: SystemStatusModalProps) {
  const [status, setStatus] = useState<SystemStatusResponse | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [actionSubmitting, setActionSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingTarget, setPendingTarget] = useState<RestartTarget | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [action, setAction] = useState<SystemRestartAction | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<number | null>(null);
  const [nowMs, setNowMs] = useState(Date.now());
  const refreshInFlightRef = useRef(false);

  const expectedConfirmation = useMemo(() => (pendingTarget ? confirmationText(pendingTarget) : ""), [pendingTarget]);
  const itemByKey = useMemo(() => new Map(status?.items.map((item) => [item.key, item]) ?? []), [status]);
  const restartCards = useMemo(
    () =>
      restartTargets.map((target) => {
        const item = target.itemKey ? itemByKey.get(target.itemKey) : null;
        return {
          ...target,
          status: item?.status ?? (target.target === "all" ? status?.status ?? "UNKNOWN" : "UNKNOWN"),
          message: item?.message ?? (target.target === "pc" ? "Reinicio completo del equipo" : status?.message ?? "Pendiente"),
        };
      }),
    [itemByKey, status]
  );
  const passiveItems = useMemo(
    () => status?.items.filter((item) => !restartTargets.some((target) => target.itemKey === item.key)) ?? [],
    [status]
  );

  async function refreshStatus() {
    if (refreshInFlightRef.current) {
      return;
    }
    refreshInFlightRef.current = true;
    setRefreshing(true);
    try {
      setStatus(await getAdminSystemStatus());
      setError(null);
      setLastRefreshedAt(Date.now());
    } catch (requestError) {
      const detail = requestError instanceof Error ? requestError.message : "No se pudo leer estado";
      setError(detail);
    } finally {
      refreshInFlightRef.current = false;
      setRefreshing(false);
    }
  }

  useEffect(() => {
    if (!open) {
      return;
    }
    void refreshStatus();
    const intervalId = window.setInterval(() => void refreshStatus(), 7000);
    const clockId = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => {
      window.clearInterval(intervalId);
      window.clearInterval(clockId);
    };
  }, [open]);

  async function confirmRestart() {
    if (!pendingTarget || confirmation.trim().toUpperCase() !== expectedConfirmation) {
      return;
    }
    setActionSubmitting(true);
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
      setActionSubmitting(false);
    }
  }

  if (!open) {
    return null;
  }

  const watchdogDisconnected = Boolean(error);
  const summaryStatus = watchdogDisconnected ? "fail" : status?.status.toLowerCase();

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

        <div className={summaryStatus ? `system-status-summary system-status-summary--${summaryStatus}` : "system-status-summary"}>
          <Power size={18} />
          <strong>{watchdogDisconnected ? "Watchdog desconectado" : status?.message ?? "Leyendo estado"}</strong>
          <span>{status?.account_mode ?? "UNKNOWN"}</span>
          <small>{elapsedLabel(lastRefreshedAt, nowMs)}</small>
          <button aria-busy={refreshing} className="toolbar-action" type="button" onClick={() => void refreshStatus()}>
            <RefreshCw className={refreshing ? "spin" : undefined} size={16} />
            Refrescar
          </button>
        </div>

        {error ? (
          <div className="compact-error system-watchdog-error">
            <ServerCrash size={18} />
            <div>
              <strong>Watchdog desconectado</strong>
              <span>{error}</span>
            </div>
            <button className="toolbar-action" type="button" onClick={() => void refreshStatus()}>
              <RefreshCw className={refreshing ? "spin" : undefined} size={16} />
              Reintentar
            </button>
          </div>
        ) : null}

        <div className="system-status-grid">
          {status ? (
            restartCards.map((card) => (
              <button
                className={`${statusClass(card.status)} system-status-card--button${card.danger ? " system-status-card--danger" : ""}`}
                disabled={status.action_running || actionSubmitting}
                key={card.target}
                type="button"
                onClick={() => {
                  setPendingTarget(card.target);
                  setConfirmation("");
                }}
              >
                <div>
                  {statusIcon(card.status)}
                  <strong>{card.label}</strong>
                  <span>{card.status}</span>
                </div>
                <p>{card.message}</p>
              </button>
            ))
          ) : error ? (
            <article className="system-status-card system-status-card--fail">
              <div>
                <ServerCrash size={18} />
                <strong>Watchdog</strong>
                <span>FAIL</span>
              </div>
              <p>No responde. Usa Reintentar.</p>
            </article>
          ) : (
            <div className="compact-warning">Cargando...</div>
          )}
        </div>

        {passiveItems.length > 0 ? (
          <div className="system-passive-grid">
            {passiveItems.map((item) => (
              <article className={statusClass(item.status)} key={item.key}>
              <div>
                {statusIcon(item.status)}
                <strong>{item.label}</strong>
                <span>{item.status}</span>
              </div>
              <p>{item.message}</p>
            </article>
            ))}
          </div>
        ) : null}

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
                disabled={confirmation.trim().toUpperCase() !== expectedConfirmation || actionSubmitting}
                type="button"
                onClick={() => void confirmRestart()}
              >
                {actionSubmitting ? "Enviando" : "Confirmar"}
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
