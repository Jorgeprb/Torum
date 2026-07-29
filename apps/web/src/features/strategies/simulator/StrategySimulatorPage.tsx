import {
  Activity,
  BarChart3,
  Bug,
  Download,
  FlaskConical,
  RefreshCw,
  ShieldCheck,
  TableProperties,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { getDrawings, type ChartDrawingRead } from "../../../services/drawings";
import {
  cancelTorumV1BacktestJob,
  getTorumV1BacktestJob,
  getTorumV1Configuration,
  startTorumV1BacktestJob,
  type TorumV1Backtest,
  type TorumV1BacktestDebugEvent,
  type TorumV1BacktestTrade,
  type TorumV1Configuration,
} from "../../../services/strategies";
import { StrategyEquityChart } from "./StrategyEquityChart";
import { StrategySimulationChart } from "./StrategySimulationChart";
import { StrategySimulationDebug } from "./StrategySimulationDebug";
import { StrategySimulationMetrics } from "./StrategySimulationMetrics";
import { StrategySimulationTrades } from "./StrategySimulationTrades";
import { StrategySimulatorLaunchCard } from "./StrategySimulatorLaunchCard";
import { StrategySimulatorSetupPanel } from "./StrategySimulatorSetupPanel";
import type {
  SimulatorDrawingOption,
  SimulatorPreset,
  SimulatorRequestSettings,
  SimulatorSetupStep,
  SimulatorSymbol,
  SimulatorValidationIssue,
} from "./simulatorTypes";

type SimulatorTab = "CHART" | "TRADES" | "DEBUG" | "CONFIG";

interface SymbolSelection {
  initialized: boolean;
  supportIds: Set<string>;
  zoneIds: Set<string>;
}

interface StoredSimulatorDraft {
  fromLocal?: string;
  overridesBySymbol?: Partial<Record<SimulatorSymbol, Record<string, unknown>>>;
  preset?: SimulatorPreset;
  request?: Partial<SimulatorRequestSettings>;
  selections?: Partial<Record<SimulatorSymbol, { initialized?: boolean; supportIds?: string[]; zoneIds?: string[] }>>;
  symbol?: SimulatorSymbol;
  toLocal?: string;
}

const defaultRequest: SimulatorRequestSettings = {
  candle_limit: 1500,
  initial_balance: 10000,
  use_session: true,
  use_unlock: true,
  use_news: true,
  use_dxy: true,
  use_operation_zones: true,
  use_supports: true,
  use_ath_capacity: true,
  use_risk: true,
  selected_operation_zone_ids: [],
  selected_support_zone_ids: [],
  entry_model: "NEXT_OPEN",
  spread_points: 0,
  slippage_points: 0,
  commission_per_lot: 0,
  close_open_trades_at_end: true,
  debug_level: "SIGNALS",
  max_debug_events: 1500,
};

const ACTIVE_BACKTEST_JOB_KEY = "torum.strategySimulator.activeJob";
const SIMULATOR_DRAFT_KEY = "torum.strategySimulator.draft.v2";

function emptySelection(): SymbolSelection {
  return { initialized: false, supportIds: new Set(), zoneIds: new Set() };
}

function abortableDelay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = window.setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      window.clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    }, { once: true });
  });
}

function effectiveParams(configuration: TorumV1Configuration, symbol: SimulatorSymbol): Record<string, unknown> {
  return { ...configuration.base_params, ...(configuration.asset_overrides[symbol] ?? {}) };
}

function operationZoneEnabled(drawing: ChartDrawingRead): boolean {
  const metadataValue = drawing.metadata.torum_v1_zone_enabled;
  const payloadValue = drawing.payload.torum_v1_zone_enabled;
  return drawing.visible && ["rectangle", "manual_zone"].includes(drawing.drawing_type) && (metadataValue === true || payloadValue === true);
}

function supportLevel(drawing: ChartDrawingRead): number | null {
  if (drawing.drawing_type !== "horizontal_line" || !drawing.visible) return null;
  const support = typeof drawing.metadata.support === "object" && drawing.metadata.support !== null
    ? drawing.metadata.support as Record<string, unknown>
    : drawing.metadata;
  const raw = Number(support.supportLevel);
  const enabled = support.enabled !== false;
  return enabled && raw >= 1 && raw <= 3 ? raw : null;
}

function csvEscape(value: unknown): string {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.split('"').join('""')}"` : text;
}

function cleanOverrides(overrides: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(overrides).filter(([, value]) => value !== "" && value !== undefined));
}

function readStoredDraft(): StoredSimulatorDraft | null {
  try {
    const raw = localStorage.getItem(SIMULATOR_DRAFT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredSimulatorDraft;
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function createSelectionFromDraft(value: StoredSimulatorDraft["selections"], symbol: SimulatorSymbol): SymbolSelection {
  const selection = value?.[symbol];
  if (!selection) return emptySelection();
  return {
    initialized: Boolean(selection.initialized),
    supportIds: new Set(Array.isArray(selection.supportIds) ? selection.supportIds.map(String) : []),
    zoneIds: new Set(Array.isArray(selection.zoneIds) ? selection.zoneIds.map(String) : []),
  };
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function StrategySimulatorPage() {
  const draftRef = useRef<StoredSimulatorDraft | null>(readStoredDraft());
  const draft = draftRef.current;
  const initialSymbol = draft?.symbol === "XAUEUR" ? "XAUEUR" : "XAUUSD";

  const [configuration, setConfiguration] = useState<TorumV1Configuration | null>(null);
  const [symbol, setSymbol] = useState<SimulatorSymbol>(initialSymbol);
  const [drawings, setDrawings] = useState<ChartDrawingRead[]>([]);
  const [drawingsLoading, setDrawingsLoading] = useState(false);
  const [request, setRequest] = useState<SimulatorRequestSettings>({ ...defaultRequest, ...(draft?.request ?? {}) });
  const [fromLocal, setFromLocalState] = useState(draft?.fromLocal ?? "");
  const [toLocal, setToLocalState] = useState(draft?.toLocal ?? "");
  const [preset, setPreset] = useState<SimulatorPreset>(draft?.preset ?? "REALISTIC");
  const [activeSetupStep, setActiveSetupStep] = useState<SimulatorSetupStep>("MARKET");
  const [overridesBySymbol, setOverridesBySymbol] = useState<Record<SimulatorSymbol, Record<string, unknown>>>(() => ({
    XAUUSD: { ...(draft?.overridesBySymbol?.XAUUSD ?? {}) },
    XAUEUR: { ...(draft?.overridesBySymbol?.XAUEUR ?? {}) },
  }));
  const [selectionBySymbol, setSelectionBySymbol] = useState<Record<SimulatorSymbol, SymbolSelection>>(() => ({
    XAUUSD: createSelectionFromDraft(draft?.selections, "XAUUSD"),
    XAUEUR: createSelectionFromDraft(draft?.selections, "XAUEUR"),
  }));
  const [result, setResult] = useState<TorumV1Backtest | null>(null);
  const [previousResult, setPreviousResult] = useState<TorumV1Backtest | null>(null);
  const [running, setRunning] = useState(false);
  const [jobProgress, setJobProgress] = useState(0);
  const [jobStage, setJobStage] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [tab, setTab] = useState<SimulatorTab>("CHART");
  const [showPullbacks, setShowPullbacks] = useState(true);
  const [showZones, setShowZones] = useState(true);
  const [showSupports, setShowSupports] = useState(true);
  const [showRejections, setShowRejections] = useState(false);
  const [focusTrade, setFocusTrade] = useState<TorumV1BacktestTrade | null>(null);
  const [focusTime, setFocusTime] = useState<string | null>(null);
  const pollAbortRef = useRef<AbortController | null>(null);
  const activeJobIdRef = useRef<string | null>(null);
  const symbolRef = useRef<SimulatorSymbol>(initialSymbol);

  const paramOverrides = overridesBySymbol[symbol];
  const currentSelection = selectionBySymbol[symbol];
  const selectedZoneIds = currentSelection.zoneIds;
  const selectedSupportIds = currentSelection.supportIds;

  const drawingOptions = useMemo<SimulatorDrawingOption[]>(() => drawings.reduce<SimulatorDrawingOption[]>((items, drawing) => {
    if (operationZoneEnabled(drawing)) {
      items.push({ id: drawing.id, label: drawing.name || `Región ${drawing.id.slice(0, 6)}`, kind: "ZONE" });
      return items;
    }
    const level = supportLevel(drawing);
    if (level != null) {
      items.push({
        id: drawing.id,
        label: drawing.name || `S${level} · ${Number(drawing.payload.price ?? 0).toFixed(2)}`,
        kind: "SUPPORT",
        level,
      });
    }
    return items;
  }, []), [drawings]);
  const zones = drawingOptions.filter((item) => item.kind === "ZONE");
  const supports = drawingOptions.filter((item) => item.kind === "SUPPORT");

  const publishedParams = useMemo(() => configuration ? effectiveParams(configuration, symbol) : {}, [configuration, symbol]);
  const mergedParams = useMemo(() => ({ ...publishedParams, ...cleanOverrides(paramOverrides) }), [paramOverrides, publishedParams]);
  const overrideCount = Object.keys(cleanOverrides(paramOverrides)).length;

  const validationIssues = useMemo<SimulatorValidationIssue[]>(() => {
    const issues: SimulatorValidationIssue[] = [];
    if (!configuration) {
      issues.push({ id: "configuration", severity: "ERROR", title: "Configuración no disponible", detail: "Espera a que se cargue la estrategia publicada.", step: "PARAMETERS" });
    }
    if (!finiteNumber(request.initial_balance) || request.initial_balance <= 0) {
      issues.push({ id: "balance", severity: "ERROR", title: "Balance inicial inválido", detail: "Introduce un balance mayor que cero.", step: "MARKET" });
    }
    if (!Number.isInteger(request.candle_limit) || request.candle_limit < 100 || request.candle_limit > 10000) {
      issues.push({ id: "candles", severity: "ERROR", title: "Cantidad de velas inválida", detail: "El rango permitido es de 100 a 10.000 velas M5.", step: "MARKET" });
    }
    if (fromLocal && Number.isNaN(new Date(fromLocal).getTime())) {
      issues.push({ id: "from-date", severity: "ERROR", title: "Fecha inicial inválida", detail: "Revisa la fecha de inicio del backtest.", step: "MARKET" });
    }
    if (toLocal && Number.isNaN(new Date(toLocal).getTime())) {
      issues.push({ id: "to-date", severity: "ERROR", title: "Fecha final inválida", detail: "Revisa la fecha final del backtest.", step: "MARKET" });
    }
    if (fromLocal && toLocal && new Date(fromLocal).getTime() >= new Date(toLocal).getTime()) {
      issues.push({ id: "date-order", severity: "ERROR", title: "Rango temporal incorrecto", detail: "La fecha inicial debe ser anterior a la final.", step: "MARKET" });
    }
    if (request.use_operation_zones && zones.length === 0 && !drawingsLoading) {
      issues.push({ id: "zones-missing", severity: "WARNING", title: "No existen regiones Torum", detail: "Con este filtro activo no habrá entradas que puedan validar una región.", step: "FILTERS" });
    } else if (request.use_operation_zones && selectedZoneIds.size === 0) {
      issues.push({ id: "zones-empty", severity: "WARNING", title: "Ninguna región seleccionada", detail: "La simulación podrá terminar sin entradas por falta de regiones permitidas.", step: "FILTERS" });
    }
    if (request.use_supports && supports.length === 0 && !drawingsLoading) {
      issues.push({ id: "supports-missing", severity: "WARNING", title: "No existen soportes S1/S2/S3", detail: "Con este filtro activo no habrá un soporte válido para las señales.", step: "FILTERS" });
    } else if (request.use_supports && selectedSupportIds.size === 0) {
      issues.push({ id: "supports-empty", severity: "WARNING", title: "Ningún soporte seleccionado", detail: "Selecciona soportes o desactiva su uso para aislar la lógica técnica.", step: "FILTERS" });
    }
    if (request.debug_level === "FULL" && request.candle_limit > 3000) {
      issues.push({ id: "full-trace", severity: "WARNING", title: "Traza completa muy amplia", detail: "Reduce las velas o aumenta el límite de eventos para evitar una traza truncada.", step: "EXECUTION" });
    }
    if (request.spread_points === 0 && request.slippage_points === 0 && request.commission_per_lot === 0 && preset !== "TECHNICAL") {
      issues.push({ id: "zero-costs", severity: "INFO", title: "Ejecución sin costes", detail: "El resultado será más optimista que una ejecución real.", step: "EXECUTION" });
    }
    const pullback = Number(mergedParams.pullback_entry_min_pct);
    const takeProfit = Number(mergedParams.take_profit_percent);
    const volume = Number(mergedParams.suggested_volume);
    if (!Number.isFinite(pullback) || pullback < 0) issues.push({ id: "pullback", severity: "ERROR", title: "Pullback mínimo inválido", detail: "Debe ser un porcentaje igual o superior a cero.", step: "PARAMETERS" });
    if (!Number.isFinite(takeProfit) || takeProfit <= 0) issues.push({ id: "take-profit", severity: "ERROR", title: "Take profit inválido", detail: "Debe ser un porcentaje mayor que cero.", step: "PARAMETERS" });
    if (!Number.isFinite(volume) || volume <= 0) issues.push({ id: "volume", severity: "ERROR", title: "Lotaje base inválido", detail: "Debe ser un número mayor que cero.", step: "PARAMETERS" });
    return issues;
  }, [configuration, drawingsLoading, fromLocal, mergedParams, preset, request, selectedSupportIds.size, selectedZoneIds.size, supports.length, toLocal, zones.length]);

  useEffect(() => {
    void getTorumV1Configuration()
      .then((value) => setConfiguration(value))
      .catch((error) => setMessage(error instanceof Error ? error.message : "No se pudo cargar la configuración"));
    return () => pollAbortRef.current?.abort();
  }, []);

  useEffect(() => {
    symbolRef.current = symbol;
    setResult(null);
    setPreviousResult(null);
    setFocusTrade(null);
    setFocusTime(null);
    setMessage(null);
    void loadDrawings(symbol);
    // loadDrawings is stable for this state transition and intentionally keyed by symbol.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  useEffect(() => {
    const jobId = sessionStorage.getItem(ACTIVE_BACKTEST_JOB_KEY);
    if (!jobId) return;
    const controller = new AbortController();
    pollAbortRef.current = controller;
    setRunning(true);
    setMessage("Reanudando simulación en curso…");
    void consumeBacktestJob(jobId, controller)
      .catch((error) => {
        if (!controller.signal.aborted) {
          sessionStorage.removeItem(ACTIVE_BACKTEST_JOB_KEY);
          activeJobIdRef.current = null;
          setMessage(error instanceof Error ? error.message : "No se pudo reanudar la simulación");
        }
      })
      .finally(() => {
        if (pollAbortRef.current === controller) {
          pollAbortRef.current = null;
          setRunning(false);
        }
      });
    return () => controller.abort();
    // Resume once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const serializedSelections = Object.fromEntries(((["XAUUSD", "XAUEUR"] as SimulatorSymbol[]).map((item) => [item, {
      initialized: selectionBySymbol[item].initialized,
      supportIds: Array.from(selectionBySymbol[item].supportIds),
      zoneIds: Array.from(selectionBySymbol[item].zoneIds),
    }])));
    const payload: StoredSimulatorDraft = {
      fromLocal,
      overridesBySymbol,
      preset,
      request,
      selections: serializedSelections,
      symbol,
      toLocal,
    };
    try {
      localStorage.setItem(SIMULATOR_DRAFT_KEY, JSON.stringify(payload));
    } catch {
      // Persisting the draft is an optional convenience and must never block simulation.
    }
  }, [fromLocal, overridesBySymbol, preset, request, selectionBySymbol, symbol, toLocal]);

  async function loadDrawings(targetSymbol = symbol) {
    setDrawingsLoading(true);
    try {
      const items = await getDrawings(targetSymbol, null, false);
      if (symbolRef.current !== targetSymbol) return;
      setDrawings(items);
      const availableZones = new Set(items.filter(operationZoneEnabled).map((item) => item.id));
      const availableSupports = new Set(items.filter((item) => supportLevel(item) != null).map((item) => item.id));
      setSelectionBySymbol((current) => {
        const previous = current[targetSymbol];
        const zoneIds = previous.initialized
          ? new Set(Array.from(previous.zoneIds).filter((id) => availableZones.has(id)))
          : new Set(availableZones);
        const supportIds = previous.initialized
          ? new Set(Array.from(previous.supportIds).filter((id) => availableSupports.has(id)))
          : new Set(availableSupports);
        return { ...current, [targetSymbol]: { initialized: true, supportIds, zoneIds } };
      });
    } catch (error) {
      if (symbolRef.current === targetSymbol) {
        setDrawings([]);
        setMessage(error instanceof Error ? error.message : "No se pudieron cargar regiones y soportes");
      }
    } finally {
      if (symbolRef.current === targetSymbol) setDrawingsLoading(false);
    }
  }

  function updateRequest<K extends keyof SimulatorRequestSettings>(key: K, value: SimulatorRequestSettings[K]) {
    setRequest((current) => ({ ...current, [key]: value }));
    setPreset("CUSTOM");
  }

  function setFromLocal(value: string) {
    setFromLocalState(value);
  }

  function setToLocal(value: string) {
    setToLocalState(value);
  }

  function setParamOverride(key: string, value: unknown) {
    setOverridesBySymbol((current) => ({ ...current, [symbol]: { ...current[symbol], [key]: value } }));
    setPreset("CUSTOM");
  }

  function clearParamOverride(key?: string) {
    setOverridesBySymbol((current) => {
      if (!key) return { ...current, [symbol]: {} };
      const next = { ...current[symbol] };
      delete next[key];
      return { ...current, [symbol]: next };
    });
    setPreset("CUSTOM");
  }

  function toggleSelected(kind: "ZONE" | "SUPPORT", id: string) {
    setSelectionBySymbol((current) => {
      const selection = current[symbol];
      const next = new Set(kind === "ZONE" ? selection.zoneIds : selection.supportIds);
      if (next.has(id)) next.delete(id); else next.add(id);
      return {
        ...current,
        [symbol]: {
          ...selection,
          initialized: true,
          ...(kind === "ZONE" ? { zoneIds: next } : { supportIds: next }),
        },
      };
    });
    setPreset("CUSTOM");
  }

  function selectAll(kind: "ZONE" | "SUPPORT", selected: boolean) {
    const values = (kind === "ZONE" ? zones : supports).map((item) => item.id);
    setSelectionBySymbol((current) => ({
      ...current,
      [symbol]: {
        ...current[symbol],
        initialized: true,
        ...(kind === "ZONE" ? { zoneIds: new Set(selected ? values : []) } : { supportIds: new Set(selected ? values : []) }),
      },
    }));
    setPreset("CUSTOM");
  }

  function applyScenario(scenario: Exclude<SimulatorPreset, "CUSTOM">) {
    setPreset(scenario);
    if (scenario === "REALISTIC") {
      setRequest((current) => ({ ...defaultRequest, candle_limit: current.candle_limit, initial_balance: current.initial_balance }));
      return;
    }
    if (scenario === "CONSERVATIVE") {
      setRequest((current) => ({
        ...current,
        entry_model: "NEXT_OPEN",
        spread_points: 3,
        slippage_points: 2,
        commission_per_lot: 7,
        use_session: true,
        use_unlock: true,
        use_news: true,
        use_dxy: true,
        use_operation_zones: true,
        use_supports: true,
        use_risk: true,
        use_ath_capacity: true,
      }));
      return;
    }
    setRequest((current) => ({
      ...current,
      use_session: false,
      use_unlock: false,
      use_news: false,
      use_dxy: false,
      use_risk: false,
      use_ath_capacity: false,
      debug_level: "FULL",
      candle_limit: Math.min(current.candle_limit, 3000),
    }));
  }

  function resetScenario() {
    setRequest({ ...defaultRequest });
    setFromLocalState("");
    setToLocalState("");
    setPreset("REALISTIC");
    setOverridesBySymbol((current) => ({ ...current, [symbol]: {} }));
    setSelectionBySymbol((current) => ({
      ...current,
      [symbol]: {
        initialized: true,
        zoneIds: new Set(zones.map((item) => item.id)),
        supportIds: new Set(supports.map((item) => item.id)),
      },
    }));
    setMessage("Escenario restaurado con valores recomendados.");
  }

  async function consumeBacktestJob(jobId: string, controller: AbortController) {
    activeJobIdRef.current = jobId;
    sessionStorage.setItem(ACTIVE_BACKTEST_JOB_KEY, jobId);
    while (!controller.signal.aborted) {
      const job = await getTorumV1BacktestJob(jobId, true, controller.signal);
      setJobProgress(job.progress);
      setJobStage(job.stage);
      setMessage(job.message);
      if (job.status === "COMPLETED") {
        if (!job.result) throw new Error("La simulación terminó sin resultado");
        setResult((current) => {
          setPreviousResult(current);
          return job.result;
        });
        setTab("CHART");
        setMessage(`Simulación completada en ${job.result.elapsed_ms.toFixed(0)} ms · ${job.result.candles_analyzed} velas`);
        sessionStorage.removeItem(ACTIVE_BACKTEST_JOB_KEY);
        activeJobIdRef.current = null;
        return;
      }
      if (job.status === "FAILED") throw new Error(job.error || "La simulación ha fallado");
      if (job.status === "CANCELLED") {
        setMessage("Simulación cancelada.");
        sessionStorage.removeItem(ACTIVE_BACKTEST_JOB_KEY);
        activeJobIdRef.current = null;
        return;
      }
      await abortableDelay(350, controller.signal);
    }
  }

  async function cancelBacktest() {
    const jobId = activeJobIdRef.current;
    pollAbortRef.current?.abort();
    pollAbortRef.current = null;
    if (jobId) {
      try {
        await cancelTorumV1BacktestJob(jobId);
      } catch {
        // The server may already have completed or discarded the job.
      }
    }
    activeJobIdRef.current = null;
    sessionStorage.removeItem(ACTIVE_BACKTEST_JOB_KEY);
    setRunning(false);
    setJobProgress(0);
    setJobStage(null);
    setMessage("Simulación cancelada.");
  }

  async function runBacktest() {
    if (!configuration) return;
    const blockingIssue = validationIssues.find((issue) => issue.severity === "ERROR");
    if (blockingIssue) {
      setMessage(`${blockingIssue.title}: ${blockingIssue.detail}`);
      if (blockingIssue.step) setActiveSetupStep(blockingIssue.step);
      return;
    }
    pollAbortRef.current?.abort();
    const controller = new AbortController();
    pollAbortRef.current = controller;
    setRunning(true);
    setJobProgress(0);
    setJobStage("QUEUED");
    setMessage("Creando simulación histórica…");
    try {
      const job = await startTorumV1BacktestJob({
        ...request,
        symbol,
        params: mergedParams,
        from_time: fromLocal ? new Date(fromLocal).toISOString() : null,
        to_time: toLocal ? new Date(toLocal).toISOString() : null,
        selected_operation_zone_ids: request.use_operation_zones ? Array.from(selectedZoneIds) : [],
        selected_support_zone_ids: request.use_supports ? Array.from(selectedSupportIds) : [],
      }, controller.signal);
      await consumeBacktestJob(job.job_id, controller);
    } catch (error) {
      if (!controller.signal.aborted) {
        sessionStorage.removeItem(ACTIVE_BACKTEST_JOB_KEY);
        activeJobIdRef.current = null;
        setMessage(error instanceof Error ? error.message : "No se pudo ejecutar la simulación");
      }
    } finally {
      if (pollAbortRef.current === controller) {
        pollAbortRef.current = null;
        setRunning(false);
      }
    }
  }

  function exportResult() {
    if (!result) return;
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `torum-backtest-${result.symbol}-${new Date(result.generated_at).toISOString().split(":").join("-")}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function exportTradesCsv() {
    if (!result) return;
    const header = ["id", "entry_time", "entry_price", "exit_time", "exit_price", "volume", "multiplier", "support", "pullback_pct", "net_profit", "mfe_pct", "mae_pct", "exit_reason"];
    const rows = result.trades.map((trade) => [trade.id, trade.entry_time, trade.entry_price, trade.exit_time, trade.exit_price, trade.volume, trade.multiplier, trade.support_level ? `S${trade.support_level}` : "", trade.pullback_pct, trade.net_profit, trade.mfe_pct, trade.mae_pct, trade.exit_reason]);
    const blob = new Blob([[header, ...rows].map((row) => row.map(csvEscape).join(",")).join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `torum-trades-${result.symbol}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function focusDebugEvent(event: TorumV1BacktestDebugEvent) {
    setFocusTrade(null);
    setFocusTime(event.time);
    setTab("CHART");
  }

  const comparison = result && previousResult ? result.metrics.net_profit - previousResult.metrics.net_profit : null;
  const configurationRevision = configuration?.configs[symbol]?.revision ?? configuration?.common_revision ?? null;

  return (
    <section className="strategy-simulator-page strategy-simulator-page--guided">
      <header className="strategy-simulator-hero strategy-simulator-hero--guided">
        <div>
          <p className="eyebrow">Laboratorio histórico · sin órdenes reales</p>
          <h2><FlaskConical size={25} /> Simulador Torum V1</h2>
          <p>Configura el escenario en cuatro pasos, ejecuta el backtest y revisa cada entrada, salida o bloqueo directamente sobre el gráfico.</p>
        </div>
        {result ? (
          <div className="strategy-simulator-hero__actions">
            <button className="toolbar-action" type="button" onClick={() => setResult(null)}><Trash2 size={16} /> Limpiar resultados</button>
            <button className="toolbar-action" type="button" onClick={exportResult}><Download size={16} /> Exportar JSON</button>
          </div>
        ) : null}
      </header>

      <div className="strategy-simulator-layout strategy-simulator-layout--guided">
        <StrategySimulatorSetupPanel
          activeStep={activeSetupStep}
          configuration={configuration}
          fromLocal={fromLocal}
          onApplyPreset={applyScenario}
          onClearDateRange={() => { setFromLocalState(""); setToLocalState(""); }}
          onClearParamOverride={clearParamOverride}
          onParamOverride={setParamOverride}
          onReloadDrawings={() => void loadDrawings(symbol)}
          onRequestChange={updateRequest}
          onSelectAll={selectAll}
          onStepChange={setActiveSetupStep}
          onSymbolChange={setSymbol}
          onToggleSelected={toggleSelected}
          overrideCount={overrideCount}
          paramOverrides={paramOverrides}
          preset={preset}
          publishedParams={publishedParams}
          request={request}
          running={running}
          selectedSupportIds={selectedSupportIds}
          selectedZoneIds={selectedZoneIds}
          setFromLocal={setFromLocal}
          setToLocal={setToLocal}
          supports={supports}
          symbol={symbol}
          toLocal={toLocal}
          zones={zones}
        />

        <main className="strategy-simulator-results">
          <StrategySimulatorLaunchCard
            configurationRevision={configurationRevision}
            fromLocal={fromLocal}
            issueCount={validationIssues.length}
            issues={validationIssues}
            onCancel={() => void cancelBacktest()}
            onEditStep={setActiveSetupStep}
            onReset={resetScenario}
            onRun={() => void runBacktest()}
            overrideCount={overrideCount}
            preset={preset}
            request={request}
            running={running}
            selectedSupportCount={selectedSupportIds.size}
            selectedZoneCount={selectedZoneIds.size}
            symbol={symbol}
            toLocal={toLocal}
          />

          {message ? <div className="notice-strip strategy-sim-notice">{running ? <RefreshCw className="is-spinning" size={15} /> : null}{message}</div> : null}
          {running ? (
            <div className="strategy-sim-progress strategy-sim-progress--prominent" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(jobProgress * 100)}>
              <div><span style={{ width: `${Math.max(2, jobProgress * 100)}%` }} /></div>
              <p><strong>{jobStage || "RUNNING"}</strong><span>{Math.round(jobProgress * 100)}%</span></p>
              <small>Puedes salir de esta pantalla: el seguimiento se recuperará al volver mientras la API siga ejecutando el trabajo.</small>
            </div>
          ) : null}

          {!result ? (
            <section className="strategy-sim-empty strategy-sim-empty--guided">
              <div className="strategy-sim-empty__visual"><BarChart3 size={46} /><span><FlaskConical size={22} /></span></div>
              <h3>Todo el simulador está en esta página</h3>
              <p>No necesitas activar ningún modo en Ajustes. Revisa el resumen superior y pulsa <strong>Ejecutar simulación</strong>.</p>
              <div className="strategy-sim-empty-steps">
                <button type="button" onClick={() => setActiveSetupStep("MARKET")}><b>1</b><span><strong>Mercado</strong><small>Activo, velas, fechas y balance.</small></span></button>
                <button type="button" onClick={() => setActiveSetupStep("FILTERS")}><b>2</b><span><strong>Condiciones</strong><small>Regiones Torum, soportes y filtros.</small></span></button>
                <button type="button" onClick={() => setActiveSetupStep("PARAMETERS")}><b>3</b><span><strong>Parámetros</strong><small>Ajustes temporales sin publicar.</small></span></button>
                <button type="button" onClick={() => setActiveSetupStep("EXECUTION")}><b>4</b><span><strong>Ejecución</strong><small>Costes, entrada y nivel de debug.</small></span></button>
              </div>
              <div className="strategy-sim-empty__safety"><ShieldCheck size={17} /> El motor histórico no crea señales, posiciones ni órdenes y nunca llama a MetaTrader.</div>
            </section>
          ) : (
            <>
              <nav className="strategy-sim-tabs">
                <button className={tab === "CHART" ? "is-active" : ""} type="button" onClick={() => setTab("CHART")}><BarChart3 size={16} /> Gráfico y métricas</button>
                <button className={tab === "TRADES" ? "is-active" : ""} type="button" onClick={() => setTab("TRADES")}><TableProperties size={16} /> Operaciones <b>{result.trades.length}</b></button>
                <button className={tab === "DEBUG" ? "is-active" : ""} type="button" onClick={() => setTab("DEBUG")}><Bug size={16} /> Depuración <b>{result.debug_events.length}</b></button>
                <button className={tab === "CONFIG" ? "is-active" : ""} type="button" onClick={() => setTab("CONFIG")}><ShieldCheck size={16} /> Cobertura</button>
              </nav>

              {result.metrics.total_trades === 0 ? (
                <div className="strategy-sim-zero-trades">
                  <Bug size={20} />
                  <div><strong>La simulación no generó operaciones</strong><span>Se detectaron {result.metrics.signals_detected} señales y {result.metrics.blocked_signals} bloqueos. Abre Depuración para ver la condición exacta que impidió cada entrada.</span></div>
                  <button type="button" onClick={() => setTab("DEBUG")}>Analizar bloqueos</button>
                </div>
              ) : null}

              {tab === "CHART" ? (
                <>
                  <div className="strategy-sim-result-toolbar">
                    <div><strong>{result.symbol} · M5</strong><span>{result.candles_analyzed} velas · {result.trades.length} operaciones · {result.elapsed_ms.toFixed(0)} ms</span></div>
                    <label><input checked={showPullbacks} type="checkbox" onChange={(event) => setShowPullbacks(event.target.checked)} /> Pullbacks</label>
                    <label><input checked={showZones} type="checkbox" onChange={(event) => setShowZones(event.target.checked)} /> Regiones</label>
                    <label><input checked={showSupports} type="checkbox" onChange={(event) => setShowSupports(event.target.checked)} /> Soportes</label>
                    <label><input checked={showRejections} type="checkbox" onChange={(event) => setShowRejections(event.target.checked)} /> Bloqueos</label>
                  </div>
                  <StrategySimulationChart result={result} focusTrade={focusTrade} focusTime={focusTime} showPullbacks={showPullbacks} showSupports={showSupports} showZones={showZones} showRejections={showRejections} onFocusCleared={() => { setFocusTrade(null); setFocusTime(null); }} />
                  <StrategySimulationMetrics metrics={result.metrics} />
                  {comparison != null ? <div className={comparison >= 0 ? "strategy-sim-comparison is-positive" : "strategy-sim-comparison is-negative"}><Activity size={16} /> Frente a la ejecución anterior: {comparison >= 0 ? "+" : ""}{comparison.toFixed(2)} de resultado neto.</div> : null}
                  <section className="settings-card"><div className="settings-card__title"><Activity size={18} /> Curva de balance y equity</div><StrategyEquityChart points={result.equity_curve} /></section>
                </>
              ) : null}
              {tab === "TRADES" ? <StrategySimulationTrades trades={result.trades} onFocus={(trade) => { setFocusTrade(trade); setFocusTime(null); setTab("CHART"); }} onExport={exportTradesCsv} /> : null}
              {tab === "DEBUG" ? <StrategySimulationDebug result={result} onFocusEvent={focusDebugEvent} /> : null}
              {tab === "CONFIG" ? (
                <section className="strategy-sim-coverage">
                  <div className="settings-card"><div className="settings-card__title"><ShieldCheck size={18} /> Cobertura del backtest</div>{Object.entries(result.coverage).map(([key, value]) => <div key={key}><strong>{key.split("_").join(" ")}</strong><span>{value}</span></div>)}</div>
                  <div className="settings-card"><div className="settings-card__title"><RefreshCw size={18} /> Escenario ejecutado</div><div><strong>Activo</strong><span>{result.symbol} · {result.timeframe}</span></div><div><strong>Velas</strong><span>{result.candles_analyzed}</span></div><div><strong>Desde</strong><span>{result.from_time ? new Date(result.from_time).toLocaleString("es-ES") : "Inicio disponible"}</span></div><div><strong>Hasta</strong><span>{result.to_time ? new Date(result.to_time).toLocaleString("es-ES") : "Último dato"}</span></div><div><strong>Revisión</strong><span>{result.config_revision ?? "—"}</span></div></div>
                  <div className="settings-card strategy-sim-effective-config"><div className="settings-card__title"><BarChart3 size={18} /> Configuración efectiva</div><pre>{JSON.stringify(result.configuration, null, 2)}</pre></div>
                  {result.warnings.length ? <div className="settings-card"><div className="settings-card__title"><Bug size={18} /> Limitaciones y avisos</div><ul>{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div> : null}
                </section>
              ) : null}
            </>
          )}
        </main>
      </div>
    </section>
  );
}
