import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  Banknote,
  CalendarDays,
  ChevronDown,
  CircleDollarSign,
  Landmark,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Trash2,
  TrendingDown,
  TrendingUp,
  WalletCards,
  X,
} from "lucide-react";

import {
  createCapitalMovement,
  deleteCapitalMovement,
  getStrategyPerformance,
  type CapitalMovementKind,
  type PerformancePoint,
  type PerformanceSummary,
} from "../../services/performance";

type RangePreset = "week" | "month" | "year" | "custom";
type MetricMode = "percent" | "money";

const presetLabels: Record<RangePreset, string> = {
  week: "Semana",
  month: "Mes",
  year: "Año",
  custom: "Fechas",
};

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function dateInputValue(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function dateTimeInputValue(date: Date): string {
  return `${dateInputValue(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function startOfLocalDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate(), 0, 0, 0, 0);
}

function endOfLocalDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate(), 23, 59, 59, 999);
}

function presetWindow(preset: Exclude<RangePreset, "custom">): { from: Date; to: Date } {
  const to = endOfLocalDay(new Date());
  const days = preset === "week" ? 7 : preset === "month" ? 30 : 365;
  const from = startOfLocalDay(new Date(to));
  from.setDate(from.getDate() - (days - 1));
  return { from, to };
}

function parseCustomWindow(fromValue: string, toValue: string): { from: Date; to: Date } | null {
  if (!fromValue || !toValue) return null;
  const from = startOfLocalDay(new Date(`${fromValue}T12:00:00`));
  const to = endOfLocalDay(new Date(`${toValue}T12:00:00`));
  return Number.isFinite(from.getTime()) && Number.isFinite(to.getTime()) && to >= from ? { from, to } : null;
}

function currencyFormatter(currency: string): Intl.NumberFormat {
  try {
    return new Intl.NumberFormat("es-ES", { style: "currency", currency, maximumFractionDigits: 2 });
  } catch {
    return new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
}

function formatSignedPercent(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "--";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function movementLabel(kind: string): string {
  if (kind === "INITIAL") return "Capital inicial";
  if (kind === "DEPOSIT") return "Aportación";
  if (kind === "WITHDRAWAL") return "Retirada";
  return "Ajuste de capital";
}

function rangeLabel(report: PerformanceSummary | null): string {
  if (!report) return "";
  const from = new Date(report.from_time);
  const to = new Date(report.to_time);
  return `${from.toLocaleDateString("es-ES", { day: "2-digit", month: "short" })} – ${to.toLocaleDateString("es-ES", { day: "2-digit", month: "short", year: "numeric" })}`;
}

function PerformanceSparkline({ points, mode }: { points: PerformancePoint[]; mode: MetricMode }) {
  const values = points.map((point) => mode === "percent" ? point.return_pct : point.cumulative_profit);
  const finite = values.filter(Number.isFinite);
  if (finite.length < 2) return <div className="performance-chart-empty">Todavía no hay cierres suficientes para dibujar la evolución.</div>;
  const width = 360;
  const height = 144;
  const padding = 10;
  const min = Math.min(...finite, 0);
  const max = Math.max(...finite, 0);
  const span = Math.max(max - min, 0.000001);
  const x = (index: number) => padding + (index / Math.max(1, values.length - 1)) * (width - padding * 2);
  const y = (value: number) => padding + ((max - value) / span) * (height - padding * 2);
  const line = values.map((value, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(" ");
  const area = `${line} L${x(values.length - 1).toFixed(1)},${height - padding} L${x(0).toFixed(1)},${height - padding} Z`;
  const positive = values[values.length - 1] >= 0;
  return (
    <svg className={positive ? "performance-sparkline performance-sparkline--positive" : "performance-sparkline performance-sparkline--negative"} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Evolución de la rentabilidad">
      <defs>
        <linearGradient id="performanceAreaGradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.28" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      {min < 0 && max > 0 ? <line className="performance-sparkline__zero" x1={padding} x2={width - padding} y1={y(0)} y2={y(0)} /> : null}
      <path className="performance-sparkline__area" d={area} />
      <path className="performance-sparkline__line" d={line} />
    </svg>
  );
}

export function StrategyPerformancePage() {
  const initialMonth = presetWindow("month");
  const [preset, setPreset] = useState<RangePreset>("month");
  const [customFrom, setCustomFrom] = useState(dateInputValue(initialMonth.from));
  const [customTo, setCustomTo] = useState(dateInputValue(initialMonth.to));
  const [metricMode, setMetricMode] = useState<MetricMode>("percent");
  const [report, setReport] = useState<PerformanceSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [capitalOpen, setCapitalOpen] = useState(false);
  const [capitalKind, setCapitalKind] = useState<CapitalMovementKind>("DEPOSIT");
  const [capitalAmount, setCapitalAmount] = useState("");
  const [capitalDate, setCapitalDate] = useState(dateTimeInputValue(new Date()));
  const [capitalNote, setCapitalNote] = useState("");
  const [capitalSaving, setCapitalSaving] = useState(false);
  const [movementsExpanded, setMovementsExpanded] = useState(false);

  const window = useMemo(() => {
    if (preset === "custom") return parseCustomWindow(customFrom, customTo);
    return presetWindow(preset);
  }, [customFrom, customTo, preset]);

  async function refresh() {
    if (!window) {
      setError("Selecciona un rango de fechas válido.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setReport(await getStrategyPerformance(window.from.toISOString(), window.to.toISOString()));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo cargar la rentabilidad.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset, customFrom, customTo]);

  const money = currencyFormatter(report?.currency ?? "EUR");
  const returnPositive = (report?.return_pct ?? 0) >= 0;
  const profitPositive = (report?.net_profit ?? 0) >= 0;
  const monthsMax = Math.max(
    0.000001,
    ...(report?.months ?? []).map((month) => Math.abs(metricMode === "percent" ? (month.return_pct ?? 0) : month.net_profit)),
  );

  async function handleCapitalSubmit(event: FormEvent) {
    event.preventDefault();
    const amount = Number(capitalAmount.replace(",", "."));
    const occurredAt = new Date(capitalDate);
    if (!Number.isFinite(amount) || amount === 0 || !Number.isFinite(occurredAt.getTime())) return;
    setCapitalSaving(true);
    setError(null);
    try {
      await createCapitalMovement({
        kind: capitalKind,
        amount,
        occurred_at: occurredAt.toISOString(),
        note: capitalNote.trim() || null,
      });
      setCapitalAmount("");
      setCapitalNote("");
      setCapitalOpen(false);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo guardar el movimiento de capital.");
    } finally {
      setCapitalSaving(false);
    }
  }

  async function handleDeleteMovement(id: number) {
    try {
      await deleteCapitalMovement(id);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo eliminar el movimiento.");
    }
  }

  return (
    <section className="performance-page">
      <header className="performance-hero-header">
        <div>
          <p className="eyebrow">Torum V1</p>
          <h2>Rentabilidad</h2>
          <p>{rangeLabel(report)}</p>
        </div>
        <button className="performance-refresh" type="button" aria-label="Actualizar rentabilidad" onClick={() => void refresh()} disabled={loading}>
          <RefreshCw size={18} className={loading ? "spin" : ""} />
        </button>
      </header>

      <div className="performance-periods" aria-label="Periodo de rentabilidad">
        {(Object.keys(presetLabels) as RangePreset[]).map((item) => (
          <button key={item} type="button" className={preset === item ? "performance-period performance-period--active" : "performance-period"} onClick={() => setPreset(item)}>
            {item === "custom" ? <CalendarDays size={15} /> : null}
            {presetLabels[item]}
          </button>
        ))}
      </div>

      {preset === "custom" ? (
        <div className="performance-custom-range">
          <label><span>Desde</span><input type="date" value={customFrom} onChange={(event) => setCustomFrom(event.target.value)} /></label>
          <label><span>Hasta</span><input type="date" value={customTo} onChange={(event) => setCustomTo(event.target.value)} /></label>
        </div>
      ) : null}

      {error ? <div className="performance-error">{error}</div> : null}

      <section className={returnPositive ? "performance-hero performance-hero--positive" : "performance-hero performance-hero--negative"}>
        <div className="performance-hero__topline">
          <div>
            <span>Rentabilidad TWR</span>
            <strong>{loading ? "…" : formatSignedPercent(report?.return_pct ?? null)}</strong>
          </div>
          <div className="performance-hero__profit">
            {profitPositive ? <ArrowUpRight size={20} /> : <ArrowDownRight size={20} />}
            <span>{loading || !report ? "--" : money.format(report.net_profit)}</span>
          </div>
        </div>
        <PerformanceSparkline points={report?.points ?? []} mode={metricMode} />
        <div className="performance-hero__footer">
          <div><span>Beneficio neto</span><strong>{report ? money.format(report.net_profit) : "--"}</strong></div>
          <div><span>Operaciones</span><strong>{report?.trades ?? "--"}</strong></div>
          <div><span>Acierto</span><strong>{report?.win_rate_pct !== null && report?.win_rate_pct !== undefined ? `${report.win_rate_pct.toFixed(0)}%` : "--"}</strong></div>
        </div>
      </section>

      <div className="performance-kpi-grid">
        <article className="performance-kpi-card">
          <span className="performance-kpi-card__icon"><WalletCards size={18} /></span>
          <div><span>Capital inicio</span><strong>{report?.capital_start !== null && report?.capital_start !== undefined ? money.format(report.capital_start) : "--"}</strong></div>
        </article>
        <article className="performance-kpi-card">
          <span className="performance-kpi-card__icon"><CircleDollarSign size={18} /></span>
          <div><span>Aportaciones netas</span><strong>{report ? money.format(report.cash_flow) : "--"}</strong></div>
        </article>
        <article className="performance-kpi-card">
          <span className="performance-kpi-card__icon"><TrendingDown size={18} /></span>
          <div><span>Drawdown realizado</span><strong>{report?.max_drawdown_pct !== null && report?.max_drawdown_pct !== undefined ? `${report.max_drawdown_pct.toFixed(2)}%` : "--"}</strong></div>
        </article>
        <article className="performance-kpi-card">
          <span className="performance-kpi-card__icon"><Sparkles size={18} /></span>
          <div><span>Mejor mes</span><strong>{report?.best_month_return_pct !== null && report?.best_month_return_pct !== undefined ? formatSignedPercent(report.best_month_return_pct) : "--"}</strong></div>
        </article>
      </div>

      <section className="performance-section">
        <div className="performance-section__heading">
          <div>
            <p className="eyebrow">Evolución</p>
            <h3>Rentabilidad por meses</h3>
          </div>
          <div className="performance-metric-toggle">
            <button className={metricMode === "percent" ? "active" : ""} type="button" onClick={() => setMetricMode("percent")}>%</button>
            <button className={metricMode === "money" ? "active" : ""} type="button" onClick={() => setMetricMode("money")}>{report?.currency ?? "€"}</button>
          </div>
        </div>
        <div className="performance-month-list">
          {(report?.months ?? []).length ? report?.months.map((month) => {
            const value = metricMode === "percent" ? (month.return_pct ?? 0) : month.net_profit;
            const width = Math.max(4, Math.abs(value) / monthsMax * 100);
            const style = { "--performance-bar-width": `${width}%` } as CSSProperties;
            return (
              <article className="performance-month" key={month.key}>
                <div className="performance-month__meta">
                  <div><strong>{month.label}</strong><span>{month.trades} operaciones</span></div>
                  <strong className={value >= 0 ? "positive" : "negative"}>{metricMode === "percent" ? formatSignedPercent(month.return_pct) : money.format(month.net_profit)}</strong>
                </div>
                <div className={value >= 0 ? "performance-month__track performance-month__track--positive" : "performance-month__track performance-month__track--negative"}>
                  <span style={style} />
                </div>
                <div className="performance-month__details">
                  <span>{month.wins} ganadoras</span><span>{month.losses} perdedoras</span>
                  {Math.abs(month.cash_flow) > 0.005 ? <span>{money.format(month.cash_flow)} capital</span> : null}
                </div>
              </article>
            );
          }) : <div className="performance-empty"><TrendingUp size={28} /><span>Aún no hay meses con operaciones cerradas en este periodo.</span></div>}
        </div>
      </section>

      <section className="performance-section performance-capital-card">
        <div className="performance-section__heading">
          <div>
            <p className="eyebrow">Capital</p>
            <h3>Aportaciones y retiradas</h3>
          </div>
          <button className="performance-add-capital" type="button" onClick={() => setCapitalOpen((current) => !current)}>
            {capitalOpen ? <X size={17} /> : <Plus size={17} />}
            {capitalOpen ? "Cerrar" : "Añadir"}
          </button>
        </div>

        <div className="performance-twr-note">
          <ShieldCheck size={20} />
          <div><strong>Las inyecciones de capital no inflan tu rentabilidad.</strong><span>Torum usa rentabilidad ponderada por tiempo (TWR): el dinero que añades cambia la base de capital, pero no se cuenta como beneficio.</span></div>
        </div>

        {report ? (
          <div className={report.basis_source === "UNAVAILABLE" ? "performance-basis performance-basis--warning" : "performance-basis"}>
            <Landmark size={18} />
            <div><strong>{report.basis_source === "EXPLICIT_LEDGER" ? "Base de capital explícita" : report.basis_source === "MT5_BALANCE_BACKSOLVE" ? "Base reconstruida desde MT5" : "Falta capital inicial"}</strong><span>{report.basis_note}</span></div>
          </div>
        ) : null}

        {capitalOpen ? (
          <form className="performance-capital-form" onSubmit={handleCapitalSubmit}>
            <label><span>Tipo</span><select value={capitalKind} onChange={(event) => setCapitalKind(event.target.value as CapitalMovementKind)}><option value="DEPOSIT">Aportación</option><option value="WITHDRAWAL">Retirada</option><option value="INITIAL">Capital inicial</option><option value="ADJUSTMENT">Ajuste</option></select></label>
            <label><span>Importe</span><div className="performance-money-input"><Banknote size={17} /><input inputMode="decimal" placeholder="0,00" value={capitalAmount} onChange={(event) => setCapitalAmount(event.target.value)} /></div></label>
            <label><span>Fecha</span><input type="datetime-local" value={capitalDate} onChange={(event) => setCapitalDate(event.target.value)} /></label>
            <label><span>Nota</span><input type="text" maxLength={500} placeholder="Opcional" value={capitalNote} onChange={(event) => setCapitalNote(event.target.value)} /></label>
            <button className="performance-capital-submit" type="submit" disabled={capitalSaving}>{capitalSaving ? "Guardando…" : "Guardar movimiento"}</button>
          </form>
        ) : null}

        <button className="performance-movement-toggle" type="button" onClick={() => setMovementsExpanded((current) => !current)}>
          <span>Movimientos detectados</span><ChevronDown size={17} className={movementsExpanded ? "rotated" : ""} />
        </button>
        {movementsExpanded ? (
          <div className="performance-movements">
            {(report?.capital_movements ?? []).length ? report?.capital_movements.map((movement) => (
              <div className="performance-movement" key={movement.id}>
                <span className={movement.amount >= 0 ? "performance-movement__icon positive" : "performance-movement__icon negative"}>{movement.amount >= 0 ? <ArrowDownRight size={17} /> : <ArrowUpRight size={17} />}</span>
                <div className="performance-movement__body"><strong>{movementLabel(movement.kind)}</strong><span>{new Date(movement.occurred_at).toLocaleString("es-ES", { day: "2-digit", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit" })} · {movement.source === "MT5" ? "Detectado por MT5" : "Manual"}{movement.note ? ` · ${movement.note}` : ""}</span></div>
                <strong className={movement.amount >= 0 ? "positive" : "negative"}>{money.format(movement.amount)}</strong>
                {movement.deletable ? <button type="button" aria-label="Eliminar movimiento" onClick={() => void handleDeleteMovement(movement.id)}><Trash2 size={16} /></button> : null}
              </div>
            )) : <div className="performance-empty performance-empty--compact"><span>No hay aportaciones ni retiradas registradas todavía.</span></div>}
          </div>
        ) : null}
      </section>

      {report?.pending_trades ? <div className="performance-footnote">Hay {report.pending_trades} cierre(s) todavía pendientes de enriquecimiento MT5; se incorporarán automáticamente cuando llegue el beneficio definitivo.</div> : null}
    </section>
  );
}
