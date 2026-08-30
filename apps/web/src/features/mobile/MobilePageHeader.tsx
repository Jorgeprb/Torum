import {
  Activity,
  BarChart3,
  CalendarClock,
  FlaskConical,
  Gauge,
  History,
  Menu,
  Settings,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

import type { MobileView } from "./AccountDrawer";

interface MobilePageHeaderProps {
  activeView: Exclude<MobileView, "chart">;
  onMenuClick: () => void;
}

const pageMeta: Record<Exclude<MobileView, "chart">, { title: string; subtitle: string; icon: LucideIcon }> = {
  performance: {
    title: "Rentabilidad",
    subtitle: "Rendimiento real de Torum V1",
    icon: TrendingUp,
  },
  history: {
    title: "Historial",
    subtitle: "Operaciones, resultados y cierres",
    icon: History,
  },
  news: {
    title: "Noticias",
    subtitle: "Contexto y bloqueos de mercado",
    icon: CalendarClock,
  },
  strategies: {
    title: "Estrategia",
    subtitle: "Reglas y ejecución de Torum V1",
    icon: Activity,
  },
  simulator: {
    title: "Simulador",
    subtitle: "Backtest y depuración histórica",
    icon: FlaskConical,
  },
  indicators: {
    title: "Indicadores",
    subtitle: "Señales y contexto técnico",
    icon: Gauge,
  },
  settings: {
    title: "Ajustes",
    subtitle: "Cuenta, estrategia y preferencias",
    icon: Settings,
  },
};

export function MobilePageHeader({ activeView, onMenuClick }: MobilePageHeaderProps) {
  const meta = pageMeta[activeView];
  const Icon = meta.icon;

  return (
    <header className={`mobile-page-header mobile-page-header--${activeView}`}>
      <button aria-label="Abrir menú" className="mobile-page-header__menu" type="button" onClick={onMenuClick}>
        <Menu size={25} />
      </button>
      <div className="mobile-page-header__identity">
        <span className="mobile-page-header__icon" aria-hidden="true">
          <Icon size={18} />
        </span>
        <div>
          <strong>{meta.title}</strong>
          <span>{meta.subtitle}</span>
        </div>
      </div>
      <div className="mobile-page-header__brand" aria-label="Torum">
        <BarChart3 size={16} />
        <span>TORUM</span>
      </div>
    </header>
  );
}
