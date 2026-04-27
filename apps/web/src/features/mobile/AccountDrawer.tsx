import { Activity, BarChart3, Gauge, History, Settings, Shield, X, type LucideIcon } from "lucide-react";

import type { MT5Status } from "../../services/market";

export type MobileView = "chart" | "strategies" | "indicators" | "settings" | "history";

interface AccountDrawerProps {
  activeView: MobileView;
  backendOk: boolean;
  marketSource: string;
  mt5Status: MT5Status | null;
  onClose: () => void;
  onNavigate: (view: MobileView) => void;
  open: boolean;
}

const navItems: Array<{ id: MobileView; label: string; icon: LucideIcon }> = [
  { id: "chart", label: "Grafico", icon: BarChart3 },
  { id: "strategies", label: "Estrategias", icon: Activity },
  { id: "indicators", label: "Indicadores", icon: Gauge },
  { id: "settings", label: "Ajustes", icon: Settings },
  { id: "history", label: "Historial", icon: History }
];

export function AccountDrawer({ activeView, backendOk, marketSource, mt5Status, onClose, onNavigate, open }: AccountDrawerProps) {
  const account = mt5Status?.account;
  return (
    <>
      <div className={open ? "drawer-backdrop drawer-backdrop--open" : "drawer-backdrop"} onClick={onClose} />
      <aside className={open ? "account-drawer account-drawer--open" : "account-drawer"} aria-hidden={!open}>
        <div className="account-drawer__header">
          <div>
            <p className="eyebrow">Torum</p>
            <h2>Cuenta</h2>
          </div>
          <button aria-label="Cerrar menu" className="mobile-icon-button" type="button" onClick={onClose}>
            <X size={22} />
          </button>
        </div>

        <section className="account-card">
          <div className="account-card__mode">
            <Shield size={18} />
            <strong>{mt5Status?.account_trade_mode ?? "UNKNOWN"}</strong>
          </div>
          <dl className="metric-list">
            <div>
              <dt>Login</dt>
              <dd>{account?.login ?? "--"}</dd>
            </div>
            <div>
              <dt>Servidor</dt>
              <dd>{account?.server ?? "--"}</dd>
            </div>
            <div>
              <dt>Balance</dt>
              <dd>{account?.balance?.toFixed(2) ?? "--"}</dd>
            </div>
            <div>
              <dt>Equity</dt>
              <dd>{account?.equity?.toFixed(2) ?? "--"}</dd>
            </div>
            <div>
              <dt>Libre</dt>
              <dd>{account?.margin_free?.toFixed(2) ?? "--"}</dd>
            </div>
            <div>
              <dt>MT5</dt>
              <dd>{mt5Status?.connected_to_mt5 ? "Conectado" : "Desconectado"}</dd>
            </div>
          </dl>
        </section>

        <nav className="drawer-nav" aria-label="Navegacion movil">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={activeView === item.id ? "drawer-nav__item drawer-nav__item--active" : "drawer-nav__item"}
                key={item.id}
                type="button"
                onClick={() => {
                  onNavigate(item.id);
                  onClose();
                }}
              >
                <Icon size={18} />
                {item.label}
              </button>
            );
          })}
        </nav>

        <section className="account-card">
          <p className="eyebrow">Estado</p>
          <dl className="metric-list">
            <div>
              <dt>Backend</dt>
              <dd>{backendOk ? "OK" : "Error"}</dd>
            </div>
            <div>
              <dt>Bridge</dt>
              <dd>{mt5Status?.connected_to_backend ? "OK" : "Pendiente"}</dd>
            </div>
            <div>
              <dt>Fuente</dt>
              <dd>{marketSource}</dd>
            </div>
          </dl>
        </section>
      </aside>
    </>
  );
}
