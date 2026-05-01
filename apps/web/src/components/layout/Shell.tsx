import { useState } from "react";
import { LogOut, Shield, Signal } from "lucide-react";

import { StatusPill } from "../ui/StatusPill";
import { TradingDashboard } from "../../features/trading/TradingDashboard";
import { accountNavItems, type MobileView } from "../../features/mobile/AccountDrawer";
import type { User } from "../../services/api";
import { useAuthStore } from "../../stores/authStore";

interface ShellProps {
  user: User;
}

export function Shell({ user }: ShellProps) {
  const logout = useAuthStore((state) => state.logout);
  const [activeView, setActiveView] = useState<MobileView>("chart");
  const activeLabel = accountNavItems.find((item) => item.id === activeView)?.label ?? "Grafico";

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
          {accountNavItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={activeView === item.id ? "nav-item nav-item--active" : "nav-item"}
                key={item.id}
                type="button"
                onClick={() => setActiveView(item.id)}
              >
                <Icon size={18} />
                {item.label}
              </button>
            );
          })}
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
            <h1>{activeLabel}</h1>
          </div>
          <div className="topbar-status">
            <Signal size={18} />
            <StatusPill label="API" tone="success" />
            <StatusPill label="MT5 desconectado" tone="warning" />
            <StatusPill label="PAPER" tone="neutral" />
          </div>
        </header>

        <TradingDashboard activeView={activeView} onActiveViewChange={setActiveView} />
      </main>
    </div>
  );
}
