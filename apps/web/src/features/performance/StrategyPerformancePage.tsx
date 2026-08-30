import { useEffect, useMemo, useState, type CSSProperties, type FormEvent, type PointerEvent } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Award,
  Banknote,
  BarChart3,
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  Flame,
  Gauge,
  Landmark,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Target,
  Trash2,
  TrendingDown,
  TrendingUp,
  Trophy,
  WalletCards,
  X,
} from "lucide-react";

import {
  createCapitalMovement,
  deleteCapitalMovement,
  getStrategyPerformance,
  type CapitalMovementKind,
  type DailyPerformance,
  type PerformanceBreakdown,
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

const calendarWeekdays = ["L", "M", "X", "J", "V", "S", "D"];

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
  const now = new Date();
  const to = endOfLocalDay(now);
  let from: Date;

  if (preset === "week") {
    from = startOfLocalDay(now);
    const mondayOffset = (from.getDay() + 6) % 7;
    from.setDate(from.getDate() - mondayOffset);
  } else if (preset === "month") {
    from = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0, 0);
  } else {
    from = new Date(now.getFullYear(), 0, 1, 0, 0, 0, 0);
  }

  return { from, to };
}

function parseCustomWindow(fromValue: string, toValue: string): { from: Date; to: Date } | null {
  if (!fromValue || !toValue) return null;
  const from = startOfLocalDay(new Date(`${fromValue}T12:00:00`));
  const to = endOfLocalDay(new Date(`${toValue}T12:00:00`));
  return Number.isFinite(from.getTime()) && Number.isFinite(to.getTime()) && to >= from ? { from, to } : null;
}

function parseCalendarDate(value: string): Date | null {
  if (!value) return null;
  const date = new Date(`${value}T12:00:00`);
  return Number.isFinite(date.getTime()) ? date : null;
}

function sameCalendarDay(a: Date | null, b: Date): boolean {
  return Boolean(a && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate());
}

function calendarDayStamp(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

function calendarGridStart(month: Date): Date {
  const first = new Date(month.getFullYear(), month.getMonth(), 1, 12, 0, 0, 0);
  const mondayOffset = (first.getDay() + 6) % 7;
  first.setDate(first.getDate() - mondayOffset);
  return first;
}

function formatCalendarSelection(value: string): string {
  const date = parseCalendarDate(value);
  return date ? date.toLocaleDateString("es-ES", { day: "2-digit", month: "short", year: "numeric" }) : "Pendiente";
}

function currencyFormatter(currency: string): Intl.NumberFormat {
  try {
    return new Intl.NumberFormat("es-ES", { style: "currency", currency, maximumFractionDigits: 2 });
  } catch {
    return new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
}

function formatSignedPercent(value: number | null, digits = 2): string {
  if (value === null || !Number.isFinite(value)) return "--";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function formatDuration(minutes: number | null): string {
  if (minutes === null || !Number.isFinite(minutes)) return "--";
  if (minutes < 60) return `${Math.max(1, Math.round(minutes))} min`;
  const hours = Math.floor(minutes / 60);
  const rest = Math.round(minutes % 60);
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
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

function PerformanceRangeCalendar({
  fromValue,
  toValue,
  visibleMonth,
  onMonthChange,
  onRangeChange,
}: {
  fromValue: string;
  toValue: string;
  visibleMonth: Date;
  onMonthChange: (month: Date) => void;
  onRangeChange: (from: string, to: string) => void;
}) {
  const from = parseCalendarDate(fromValue);
  const to = parseCalendarDate(toValue);
  const start = calendarGridStart(visibleMonth);
  const days = Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return date;
  });
  const fromStamp = from ? calendarDayStamp(from) : null;
  const toStamp = to ? calendarDayStamp(to) : null;

  function selectDate(date: Date): void {
    if (date.getMonth() !== visibleMonth.getMonth() || date.getFullYear() !== visibleMonth.getFullYear()) {
      onMonthChange(new Date(date.getFullYear(), date.getMonth(), 1, 12, 0, 0, 0));
    }
    const key = dateInputValue(date);
    if (!from || to) {
      onRangeChange(key, "");
      return;
    }
    if (calendarDayStamp(date) < calendarDayStamp(from)) {
      onRangeChange(key, "");
      return;
    }
    onRangeChange(fromValue, key);
  }

  return (
    <section className="performance-range-calendar" aria-label="Seleccionar rango de fechas">
      <div className="performance-range-calendar__header">
        <button type="button" aria-label="Mes anterior" onClick={() => onMonthChange(new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() - 1, 1, 12))}><ChevronLeft size={18} /></button>
        <strong>{visibleMonth.toLocaleDateString("es-ES", { month: "long", year: "numeric" })}</strong>
        <button type="button" aria-label="Mes siguiente" onClick={() => onMonthChange(new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + 1, 1, 12))}><ChevronRight size={18} /></button>
      </div>
      <div className="performance-range-calendar__weekdays">
        {calendarWeekdays.map((day) => <span key={day}>{day}</span>)}
      </div>
      <div className="performance-range-calendar__days">
        {days.map((day) => {
          const stamp = calendarDayStamp(day);
          const isStart = sameCalendarDay(from, day);
          const isEnd = sameCalendarDay(to, day);
          const inRange = fromStamp !== null && toStamp !== null && stamp > fromStamp && stamp < toStamp;
          const outside = day.getMonth() !== visibleMonth.getMonth();
          const today = sameCalendarDay(new Date(), day);
          const classes = [
            "performance-range-calendar__day",
            outside ? "performance-range-calendar__day--outside" : "",
            inRange ? "performance-range-calendar__day--range" : "",
            isStart ? "performance-range-calendar__day--start" : "",
            isEnd ? "performance-range-calendar__day--end" : "",
            today ? "performance-range-calendar__day--today" : "",
          ].filter(Boolean).join(" ");
          return <button key={dateInputValue(day)} className={classes} type="button" onClick={() => selectDate(day)}>{day.getDate()}</button>;
        })}
      </div>
      <div className="performance-range-calendar__selection">
        <div><span>Inicio</span><strong>{formatCalendarSelection(fromValue)}</strong></div>
        <div><span>Fin</span><strong>{formatCalendarSelection(toValue)}</strong></div>
      </div>
      <p className="performance-range-calendar__hint">
        {!fromValue || toValue ? "Pulsa una fecha para iniciar un nuevo rango." : "Ahora selecciona la fecha final. Puedes cambiar de mes sin perder el inicio."}
      </p>
    </section>
  );
}

function PerformanceGrowthChart({ points, mode, money }: { points: PerformancePoint[]; mode: MetricMode; money: Intl.NumberFormat }) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const values = points.map((point) => mode === "percent" ? point.return_pct : point.cumulative_profit);
  const finite = values.filter(Number.isFinite);
  if (finite.length < 2) return <div className="performance-chart-empty">Todavía no hay cierres suficientes para dibujar la evolución.</div>;

  const width = 760;
  const height = 250;
  const left = 48;
  const right = 14;
  const top = 18;
  const bottom = 34;
  const minValue = Math.min(...finite, 0);
  const maxValue = Math.max(...finite, 0);
  const paddingValue = Math.max((maxValue - minValue) * 0.12, mode === "percent" ? 0.05 : 1);
  const min = minValue - paddingValue;
  const max = maxValue + paddingValue;
  const span = Math.max(max - min, 0.000001);
  const x = (index: number) => left + (index / Math.max(1, values.length - 1)) * (width - left - right);
  const y = (value: number) => top + ((max - value) / span) * (height - top - bottom);
  const line = values.map((value, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(" ");
  const area = `${line} L${x(values.length - 1).toFixed(1)},${height - bottom} L${x(0).toFixed(1)},${height - bottom} Z`;
  const lastValue = values[values.length - 1];
  const positive = lastValue >= 0;
  const ticks = Array.from({ length: 5 }, (_, index) => max - (index / 4) * span);
  const dateIndices = Array.from(new Set([0, Math.floor((points.length - 1) / 2), points.length - 1]));

  function handlePointer(event: PointerEvent<SVGSVGElement>): void {
    const rect = event.currentTarget.getBoundingClientRect();
    if (!rect.width) return;
    const local = ((event.clientX - rect.left) / rect.width) * width;
    const ratio = Math.max(0, Math.min(1, (local - left) / (width - left - right)));
    setSelectedIndex(Math.round(ratio * Math.max(0, points.length - 1)));
  }

  const selected = selectedIndex === null ? null : points[selectedIndex];
  const selectedValue = selectedIndex === null ? null : values[selectedIndex];

  return (
    <div className="performance-growth-chart">
      {selected && selectedValue !== null ? (
        <div className="performance-growth-chart__tooltip">
          <span>{new Date(selected.time).toLocaleString("es-ES", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
          <strong className={selectedValue >= 0 ? "positive" : "negative"}>{mode === "percent" ? formatSignedPercent(selectedValue) : money.format(selectedValue)}</strong>
        </div>
      ) : <div className="performance-growth-chart__tooltip performance-growth-chart__tooltip--hint"><span>Toca o desliza por el gráfico para inspeccionar</span></div>}
      <svg className={positive ? "performance-growth-chart__svg positive" : "performance-growth-chart__svg negative"} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" onPointerMove={handlePointer} onPointerDown={handlePointer} onPointerLeave={() => setSelectedIndex(null)} role="img" aria-label="Curva de rentabilidad acumulada">
        <defs>
          <linearGradient id="performanceGrowthArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.24" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0.01" />
          </linearGradient>
        </defs>
        {ticks.map((tick) => (
          <g key={tick}>
            <line className="performance-growth-chart__grid" x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} />
            <text className="performance-growth-chart__axis" x={left - 8} y={y(tick) + 3} textAnchor="end">{mode === "percent" ? `${tick.toFixed(1)}%` : money.format(tick)}</text>
          </g>
        ))}
        {min < 0 && max > 0 ? <line className="performance-growth-chart__zero" x1={left} x2={width - right} y1={y(0)} y2={y(0)} /> : null}
        <path className="performance-growth-chart__area" d={area} />
        <path className="performance-growth-chart__line" d={line} />
        {dateIndices.map((index) => (
          <text key={index} className="performance-growth-chart__date" x={x(index)} y={height - 8} textAnchor={index === 0 ? "start" : index === points.length - 1 ? "end" : "middle"}>
            {new Date(points[index].time).toLocaleDateString("es-ES", { day: "2-digit", month: "short" })}
          </text>
        ))}
        {selectedIndex !== null && selected ? (
          <g>
            <line className="performance-growth-chart__cursor" x1={x(selectedIndex)} x2={x(selectedIndex)} y1={top} y2={height - bottom} />
            <circle className="performance-growth-chart__point" cx={x(selectedIndex)} cy={y(values[selectedIndex])} r="5" />
          </g>
        ) : null}
      </svg>
    </div>
  );
}

function MultiplierBadges({ day }: { day: DailyPerformance }) {
  return (
    <div className="performance-calendar__multipliers" aria-label="Multiplicadores del día">
      {day.x1 ? <span className="x1">x1 · {day.x1}</span> : null}
      {day.x2 ? <span className="x2">x2 · {day.x2}</span> : null}
      {day.x3 ? <span className="x3">x3 · {day.x3}</span> : null}
    </div>
  );
}

function PerformanceTradingCalendar({ report, money }: { report: PerformanceSummary; money: Intl.NumberFormat }) {
  const reportEnd = new Date(report.to_time);
  const [visibleMonth, setVisibleMonth] = useState(() => new Date(reportEnd.getFullYear(), reportEnd.getMonth(), 1, 12));
  const [selectedDayKey, setSelectedDayKey] = useState<string | null>(null);

  useEffect(() => {
    const end = new Date(report.to_time);
    setVisibleMonth(new Date(end.getFullYear(), end.getMonth(), 1, 12));
    setSelectedDayKey(null);
  }, [report.from_time, report.to_time]);

  const dayMap = useMemo(() => new Map(report.days.map((day) => [day.date, day])), [report.days]);
  const start = calendarGridStart(visibleMonth);
  const grid = Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return date;
  });
  const selectedDay = selectedDayKey ? dayMap.get(selectedDayKey) ?? null : null;
  const reportStartStamp = new Date(report.from_time).getTime();
  const reportEndStamp = new Date(report.to_time).getTime();
  const previousMonthEnd = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 0, 23, 59, 59).getTime();
  const nextMonthStart = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + 1, 1).getTime();
  const canPrevious = previousMonthEnd >= reportStartStamp;
  const canNext = nextMonthStart <= reportEndStamp;

  return (
    <section className="performance-section performance-calendar-card">
      <div className="performance-section__heading">
        <div>
          <p className="eyebrow">Diario</p>
          <h3>Calendario de operaciones</h3>
          <p className="performance-section__subtitle">Resultado realizado al cierre · TWR diario</p>
        </div>
        <div className="performance-calendar__month-nav">
          <button type="button" aria-label="Mes anterior" disabled={!canPrevious} onClick={() => setVisibleMonth(new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() - 1, 1, 12))}><ChevronLeft size={17} /></button>
          <strong>{visibleMonth.toLocaleDateString("es-ES", { month: "short", year: "numeric" })}</strong>
          <button type="button" aria-label="Mes siguiente" disabled={!canNext} onClick={() => setVisibleMonth(new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + 1, 1, 12))}><ChevronRight size={17} /></button>
        </div>
      </div>

      <div className="performance-calendar__legend">
        <span><i className="win" /> Ganancia</span><span><i className="loss" /> Pérdida</span><span><i className="flat" /> Sin resultado</span>
      </div>
      <div className="performance-calendar__weekdays">{calendarWeekdays.map((day) => <span key={day}>{day}</span>)}</div>
      <div className="performance-calendar__grid">
        {grid.map((date) => {
          const key = dateInputValue(date);
          const day = dayMap.get(key);
          const outside = date.getMonth() !== visibleMonth.getMonth();
          const intensity = day ? Math.min(1, 0.18 + Math.abs(day.return_pct ?? 0) / 2.5) : 0;
          const state = day ? day.net_profit > 0 ? "win" : day.net_profit < 0 ? "loss" : "flat" : "empty";
          const style = { "--performance-day-intensity": (0.035 + intensity * 0.13).toFixed(3) } as CSSProperties;
          return (
            <button
              key={key}
              type="button"
              disabled={outside || !day}
              className={`performance-calendar__day performance-calendar__day--${state}${outside ? " performance-calendar__day--outside" : ""}${selectedDayKey === key ? " selected" : ""}`}
              style={style}
              onClick={() => setSelectedDayKey((current) => current === key ? null : key)}
            >
              <span className="performance-calendar__date">{date.getDate()}</span>
              {day ? (
                <>
                  <strong>{formatSignedPercent(day.return_pct, 2)}</strong>
                  <small>{day.trades} {day.trades === 1 ? "op" : "ops"}{day.pending ? ` · ${day.pending} pendiente${day.pending === 1 ? "" : "s"}` : ""}</small>
                  <MultiplierBadges day={day} />
                </>
              ) : null}
            </button>
          );
        })}
      </div>

      {selectedDay ? (
        <div className="performance-day-detail">
          <div className="performance-day-detail__header">
            <div>
              <span>{parseCalendarDate(selectedDay.date)?.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" })}</span>
              <strong className={selectedDay.net_profit >= 0 ? "positive" : "negative"}>{formatSignedPercent(selectedDay.return_pct)} · {money.format(selectedDay.net_profit)}</strong>
            </div>
            <div className="performance-day-detail__score"><span>{selectedDay.wins} G</span><span>{selectedDay.losses} P</span></div>
          </div>
          <MultiplierBadges day={selectedDay} />
          <div className="performance-day-detail__trades">
            {selectedDay.trades_detail.map((trade) => (
              <article key={trade.position_id} className="performance-day-trade">
                <span className={`performance-day-trade__multiplier x${trade.multiplier}`}>x{trade.multiplier}</span>
                <div className="performance-day-trade__main">
                  <strong>{trade.symbol}</strong>
                  <span>{new Date(trade.closed_at).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid" })} · {trade.volume.toFixed(2)} lotes · {formatDuration(trade.duration_minutes)}</span>
                  <small>{trade.open_price.toFixed(2)} → {trade.close_price !== null ? trade.close_price.toFixed(2) : "--"}</small>
                </div>
                {trade.pending || trade.net_profit === null ? (
                  <strong className="performance-day-trade__pending">Pendiente MT5</strong>
                ) : (
                  <strong className={trade.net_profit >= 0 ? "positive" : "negative"}>{money.format(trade.net_profit)}</strong>
                )}
              </article>
            ))}
          </div>
        </div>
      ) : <p className="performance-calendar__hint">Toca un día con operaciones para ver cada cierre, su multiplicador y resultado.</p>}
    </section>
  );
}

function BreakdownCard({ title, items, money }: { title: string; items: PerformanceBreakdown[]; money: Intl.NumberFormat }) {
  const maxTrades = Math.max(1, ...items.map((item) => item.trades));
  return (
    <section className="performance-breakdown-card">
      <div className="performance-breakdown-card__heading"><strong>{title}</strong><span>{items.reduce((sum, item) => sum + item.trades, 0)} cierres</span></div>
      <div className="performance-breakdown-card__list">
        {items.map((item) => {
          const style = { "--performance-breakdown-width": `${(item.trades / maxTrades) * 100}%` } as CSSProperties;
          return (
            <article key={item.key} className="performance-breakdown-row">
              <div className="performance-breakdown-row__meta"><strong>{item.label}</strong><span>{item.trades} ops · {item.win_rate_pct !== null ? `${item.win_rate_pct.toFixed(0)}% acierto` : "--"}{item.pending ? ` · ${item.pending} pendientes` : ""}</span></div>
              <strong className={item.net_profit >= 0 ? "positive" : "negative"}>{money.format(item.net_profit)}</strong>
              <div className="performance-breakdown-row__track"><span style={style} /></div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function StrategyPerformancePage() {
  const initialMonth = presetWindow("month");
  const [preset, setPreset] = useState<RangePreset>("month");
  const [customFrom, setCustomFrom] = useState(dateInputValue(initialMonth.from));
  const [customTo, setCustomTo] = useState(dateInputValue(initialMonth.to));
  const [customCalendarMonth, setCustomCalendarMonth] = useState(() => new Date(initialMonth.to.getFullYear(), initialMonth.to.getMonth(), 1, 12));
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
      if (preset === "custom" && (!customFrom || !customTo)) {
        setError(null);
        return;
      }
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

  useEffect(() => {
    const handleAccountChange = () => void refresh();
    globalThis.window.addEventListener("torum:mt5-account-changed", handleAccountChange);
    return () => globalThis.window.removeEventListener("torum:mt5-account-changed", handleAccountChange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset, customFrom, customTo]);

  const money = currencyFormatter(report?.currency ?? "EUR");
  const returnPositive = (report?.return_pct ?? 0) >= 0;
  const profitPositive = (report?.net_profit ?? 0) >= 0;
  const monthsMax = Math.max(0.000001, ...(report?.months ?? []).map((month) => Math.abs(metricMode === "percent" ? (month.return_pct ?? 0) : month.net_profit)));

  async function handleCapitalSubmit(event: FormEvent) {
    event.preventDefault();
    const amount = Number(capitalAmount.replace(",", "."));
    const occurredAt = new Date(capitalDate);
    if (!Number.isFinite(amount) || amount === 0 || !Number.isFinite(occurredAt.getTime())) return;
    setCapitalSaving(true);
    setError(null);
    try {
      await createCapitalMovement({ kind: capitalKind, amount, occurred_at: occurredAt.toISOString(), note: capitalNote.trim() || null });
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
          <p className="eyebrow">Cuenta MT5 · Realizado</p>
          <h2>Rentabilidad</h2>
          <p>{rangeLabel(report)}</p>
        </div>
        <button className="performance-refresh" type="button" aria-label="Actualizar rentabilidad" onClick={() => void refresh()} disabled={loading}><RefreshCw size={18} className={loading ? "spin" : ""} /></button>
      </header>

      <div className="performance-periods" aria-label="Periodo de rentabilidad">
        {(Object.keys(presetLabels) as RangePreset[]).map((item) => (
          <button key={item} type="button" className={preset === item ? "performance-period performance-period--active" : "performance-period"} onClick={() => setPreset(item)}>
            {item === "custom" ? <CalendarDays size={15} /> : null}{presetLabels[item]}
          </button>
        ))}
      </div>

      {preset === "custom" ? (
        <PerformanceRangeCalendar fromValue={customFrom} toValue={customTo} visibleMonth={customCalendarMonth} onMonthChange={setCustomCalendarMonth} onRangeChange={(from, to) => { setCustomFrom(from); setCustomTo(to); setError(null); }} />
      ) : null}

      {error ? <div className="performance-error">{error}</div> : null}

      <section className={returnPositive ? "performance-hero performance-hero--positive" : "performance-hero performance-hero--negative"}>
        <div className="performance-hero__topline">
          <div><span>{preset === "month" ? "Rentabilidad mes en curso" : "Rentabilidad TWR"}</span><strong>{loading ? "…" : formatSignedPercent(report?.return_pct ?? null)}</strong></div>
          <div className="performance-hero__profit">{profitPositive ? <ArrowUpRight size={20} /> : <ArrowDownRight size={20} />}<span>{loading || !report ? "--" : money.format(report.net_profit)}</span></div>
        </div>
        <div className="performance-chart-toolbar">
          <div><BarChart3 size={16} /><span>Curva acumulada</span></div>
          <div className="performance-metric-toggle"><button type="button" className={metricMode === "percent" ? "active" : ""} onClick={() => setMetricMode("percent")}>%</button><button type="button" className={metricMode === "money" ? "active" : ""} onClick={() => setMetricMode("money")}>€</button></div>
        </div>
        <PerformanceGrowthChart points={report?.points ?? []} mode={metricMode} money={money} />
        <div className="performance-hero__footer">
          <div><span>Beneficio neto</span><strong>{report ? money.format(report.net_profit) : "--"}</strong></div>
          <div><span>Operaciones</span><strong>{report?.trades ?? "--"}</strong></div>
          <div><span>Acierto</span><strong>{report?.win_rate_pct !== null && report?.win_rate_pct !== undefined ? `${report.win_rate_pct.toFixed(0)}%` : "--"}</strong></div>
          <div><span>Drawdown máx.</span><strong className="negative">{report?.max_drawdown_pct !== null && report?.max_drawdown_pct !== undefined ? `${Math.abs(report.max_drawdown_pct).toFixed(2)}%` : "--"}</strong></div>
        </div>
      </section>

      <div className="performance-kpi-grid performance-kpi-grid--primary">
        <article className="performance-kpi-card"><span className="performance-kpi-card__icon"><Target size={18} /></span><div><span>Profit factor</span><strong>{report ? report.profit_factor !== null ? report.profit_factor.toFixed(2) : report.gross_profit > 0 && report.losses === 0 ? "∞" : "--" : "--"}</strong></div></article>
        <article className="performance-kpi-card"><span className="performance-kpi-card__icon"><Sparkles size={18} /></span><div><span>Expectativa / op.</span><strong className={(report?.expectancy ?? 0) >= 0 ? "positive" : "negative"}>{report?.expectancy !== null && report?.expectancy !== undefined ? money.format(report.expectancy) : "--"}</strong></div></article>
        <article className="performance-kpi-card"><span className="performance-kpi-card__icon"><Trophy size={18} /></span><div><span>Mejor operación</span><strong className="positive">{report?.best_trade !== null && report?.best_trade !== undefined ? money.format(report.best_trade) : "--"}</strong></div></article>
        <article className="performance-kpi-card"><span className="performance-kpi-card__icon"><TrendingDown size={18} /></span><div><span>Peor operación</span><strong className="negative">{report?.worst_trade !== null && report?.worst_trade !== undefined ? money.format(report.worst_trade) : "--"}</strong></div></article>
      </div>

      {report ? <PerformanceTradingCalendar report={report} money={money} /> : null}

      <section className="performance-section">
        <div className="performance-section__heading">
          <div><p className="eyebrow">Calidad</p><h3>Estadísticas de la operativa</h3><p className="performance-section__subtitle">Todas las operaciones cerradas de la cuenta activa, automáticas o manuales.</p></div>
          <Activity size={21} className="performance-heading-icon" />
        </div>
        <div className="performance-stats-grid">
          <article><span><TrendingUp size={16} /> Ganancia media</span><strong className="positive">{report?.average_win !== null && report?.average_win !== undefined ? money.format(report.average_win) : "--"}</strong></article>
          <article><span><TrendingDown size={16} /> Pérdida media</span><strong className="negative">{report?.average_loss !== null && report?.average_loss !== undefined ? money.format(report.average_loss) : "--"}</strong></article>
          <article><span><CalendarDays size={16} /> Días positivos</span><strong>{report ? `${report.profitable_days}` : "--"}</strong><small>{report ? `${report.losing_days} negativos` : ""}</small></article>
          <article><span><Award size={16} /> Mejor día</span><strong className="positive">{formatSignedPercent(report?.best_day_pct ?? null)}</strong><small>{report?.best_day_profit !== null && report?.best_day_profit !== undefined ? money.format(report.best_day_profit) : ""}</small></article>
          <article><span><Gauge size={16} /> Peor día</span><strong className="negative">{formatSignedPercent(report?.worst_day_pct ?? null)}</strong><small>{report?.worst_day_profit !== null && report?.worst_day_profit !== undefined ? money.format(report.worst_day_profit) : ""}</small></article>
          <article><span><Flame size={16} /> Rachas</span><strong>{report ? `${report.max_win_streak} G · ${report.max_loss_streak} P` : "--"}</strong><small>{report?.current_streak ? `Actual: ${report.current_streak} ${report.current_streak_type === "WIN" ? "ganadoras" : "perdedoras"}` : "Sin racha"}</small></article>
        </div>
      </section>

      <div className="performance-breakdowns">
        <BreakdownCard title="Por tamaño de entrada" items={report?.multiplier_breakdown ?? []} money={money} />
        <BreakdownCard title="Por activo" items={report?.symbol_breakdown ?? []} money={money} />
      </div>

      <div className="performance-kpi-grid">
        <article className="performance-kpi-card"><span className="performance-kpi-card__icon"><WalletCards size={18} /></span><div><span>Capital inicio</span><strong>{report?.capital_start !== null && report?.capital_start !== undefined ? money.format(report.capital_start) : "--"}</strong></div></article>
        <article className="performance-kpi-card"><span className="performance-kpi-card__icon"><CircleDollarSign size={18} /></span><div><span>Aportaciones netas</span><strong>{report ? money.format(report.cash_flow) : "--"}</strong></div></article>
        <article className="performance-kpi-card"><span className="performance-kpi-card__icon"><TrendingUp size={18} /></span><div><span>Ganancia bruta</span><strong className="positive">{report ? money.format(report.gross_profit) : "--"}</strong></div></article>
        <article className="performance-kpi-card"><span className="performance-kpi-card__icon"><TrendingDown size={18} /></span><div><span>Pérdida bruta</span><strong className="negative">{report ? money.format(report.gross_loss) : "--"}</strong></div></article>
      </div>

      <section className="performance-section">
        <div className="performance-section__heading">
          <div><p className="eyebrow">Mes a mes</p><h3>Evolución mensual</h3></div>
          <div className="performance-metric-toggle"><button type="button" className={metricMode === "percent" ? "active" : ""} onClick={() => setMetricMode("percent")}>%</button><button type="button" className={metricMode === "money" ? "active" : ""} onClick={() => setMetricMode("money")}>€</button></div>
        </div>
        <div className="performance-month-list">
          {(report?.months ?? []).length ? report?.months.map((month) => {
            const value = metricMode === "percent" ? (month.return_pct ?? 0) : month.net_profit;
            const style = { "--performance-bar-width": `${Math.max(2, Math.abs(value) / monthsMax * 100)}%` } as CSSProperties;
            return (
              <article className="performance-month" key={month.key}>
                <div className="performance-month__meta"><div><strong>{month.label}</strong><span>{month.trades} operaciones</span></div><strong className={value >= 0 ? "positive" : "negative"}>{metricMode === "percent" ? formatSignedPercent(month.return_pct) : money.format(month.net_profit)}</strong></div>
                <div className={value >= 0 ? "performance-month__track performance-month__track--positive" : "performance-month__track performance-month__track--negative"}><span style={style} /></div>
                <div className="performance-month__details"><span>{month.wins} ganadoras</span><span>{month.losses} perdedoras</span>{month.pending ? <span>{month.pending} pendientes MT5</span> : null}{Math.abs(month.cash_flow) > 0.005 ? <span>{money.format(month.cash_flow)} capital</span> : null}</div>
              </article>
            );
          }) : <div className="performance-empty"><TrendingUp size={28} /><span>Aún no hay meses con operaciones cerradas en este periodo.</span></div>}
        </div>
      </section>

      <section className="performance-section performance-capital-card">
        <div className="performance-section__heading">
          <div><p className="eyebrow">Capital</p><h3>Aportaciones y retiradas</h3></div>
          <button className="performance-add-capital" type="button" onClick={() => setCapitalOpen((current) => !current)}>{capitalOpen ? <X size={17} /> : <Plus size={17} />}{capitalOpen ? "Cerrar" : "Añadir"}</button>
        </div>
        <div className="performance-twr-note"><ShieldCheck size={20} /><div><strong>Las inyecciones de capital no inflan tu rentabilidad.</strong><span>Torum usa rentabilidad ponderada por tiempo (TWR): el dinero que añades cambia la base de capital, pero no se cuenta como beneficio.</span></div></div>
        {report ? <div className={report.basis_source === "UNAVAILABLE" ? "performance-basis performance-basis--warning" : "performance-basis"}><Landmark size={18} /><div><strong>{report.basis_source === "EXPLICIT_LEDGER" ? "Base de capital explícita" : report.basis_source === "MT5_BALANCE_BACKSOLVE" ? "Base reconstruida desde MT5" : "Falta capital inicial"}</strong><span>{report.basis_note}</span></div></div> : null}
        {capitalOpen ? (
          <form className="performance-capital-form" onSubmit={handleCapitalSubmit}>
            <label><span>Tipo</span><select value={capitalKind} onChange={(event) => setCapitalKind(event.target.value as CapitalMovementKind)}><option value="DEPOSIT">Aportación</option><option value="WITHDRAWAL">Retirada</option><option value="INITIAL">Capital inicial</option><option value="ADJUSTMENT">Ajuste</option></select></label>
            <label><span>Importe</span><div className="performance-money-input"><Banknote size={17} /><input inputMode="decimal" placeholder="0,00" value={capitalAmount} onChange={(event) => setCapitalAmount(event.target.value)} /></div></label>
            <label><span>Fecha</span><input type="datetime-local" value={capitalDate} onChange={(event) => setCapitalDate(event.target.value)} /></label>
            <label><span>Nota</span><input type="text" maxLength={500} placeholder="Opcional" value={capitalNote} onChange={(event) => setCapitalNote(event.target.value)} /></label>
            <button className="performance-capital-submit" type="submit" disabled={capitalSaving}>{capitalSaving ? "Guardando…" : "Guardar movimiento"}</button>
          </form>
        ) : null}
        <button className="performance-movement-toggle" type="button" onClick={() => setMovementsExpanded((current) => !current)}><span>Movimientos detectados</span><ChevronDown size={17} className={movementsExpanded ? "rotated" : ""} /></button>
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

      {report?.pending_trades ? <div className="performance-footnote"><Clock3 size={14} /> Hay {report.pending_trades} cierre(s) todavía pendientes de enriquecimiento MT5; se incorporarán automáticamente cuando llegue el beneficio definitivo.</div> : null}
    </section>
  );
}
