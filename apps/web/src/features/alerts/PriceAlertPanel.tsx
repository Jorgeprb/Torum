import { Bell, Trash2 } from "lucide-react";

import type { PriceAlertRead } from "../../services/alerts";

interface PriceAlertPanelProps {
  activeAlerts: PriceAlertRead[];
  history: PriceAlertRead[];
  onCancel: (alertId: string) => void;
}

export function PriceAlertPanel({ activeAlerts, history, onCancel }: PriceAlertPanelProps) {
  return (
    <section className="panel price-alert-panel">
      <div className="panel-title">
        <Bell size={18} />
        Alertas BELOW
      </div>
      <div className="alert-list">
        {activeAlerts.length === 0 ? <div className="table-empty">No hay alertas activas</div> : null}
        {activeAlerts.map((alert) => (
          <div className="alert-row" key={alert.id}>
            <div>
              <strong>{alert.internal_symbol}</strong>
              <span>Precio &lt;= {alert.target_price.toFixed(2)}</span>
            </div>
            <button aria-label="Cancelar alerta" className="icon-only" type="button" onClick={() => onCancel(alert.id)}>
              <Trash2 size={15} />
            </button>
          </div>
        ))}
      </div>
      <div className="alert-history">
        <p className="eyebrow">Historial</p>
        {history.slice(0, 4).map((alert) => (
          <div className="alert-history__item" key={alert.id}>
            <span>{alert.status}</span>
            <span>{alert.triggered_price ? alert.triggered_price.toFixed(2) : alert.target_price.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
