import { Activity, Bell, Gauge, LogOut, Settings, Shield, Signal } from "lucide-react";

import { StatusPill } from "../ui/StatusPill";
import { TradingDashboard } from "../../features/trading/TradingDashboard";
import type { User } from "../../services/api";
import { useAuthStore } from "../../stores/authStore";

interface ShellProps {
  user: User;
}

export function Shell({ user }: ShellProps) {
  const logout = useAuthStore((state) => state.logout);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark">T</div>
          <div>
            <div className="brand-name">Torum</div>
            <div className="brand-subtitle">Gold Terminal</div>
          </div>
        </div>

        <nav className="nav-list" aria-label="Principal">
          <button className="nav-item nav-item--active" type="button">
            <Activity size={18} />
            Trading
          </button>
          <button className="nav-item" type="button">
            <Gauge size={18} />
            Indicadores
          </button>
          <button className="nav-item" type="button">
            <Bell size={18} />
            Alertas
          </button>
          <button className="nav-item" type="button">
            <Settings size={18} />
            Configuracion
          </button>
        </nav>

        <div className="sidebar-footer">
          <div className="user-chip">
            <Shield size={16} />
            <span>{user.username}</span>
            <StatusPill label={user.role.toUpperCase()} tone={user.role === "admin" ? "warning" : "neutral"} />
          </div>
          <button className="icon-text-button" type="button" onClick={logout}>
            <LogOut size={18} />
            Salir
          </button>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Terminal</p>
            <h1>Trading</h1>
          </div>
          <div className="topbar-status">
            <Signal size={18} />
            <StatusPill label="API" tone="success" />
            <StatusPill label="MT5 desconectado" tone="warning" />
            <StatusPill label="PAPER" tone="neutral" />
          </div>
        </header>

        <TradingDashboard />
      </main>
    </div>
  );
}
