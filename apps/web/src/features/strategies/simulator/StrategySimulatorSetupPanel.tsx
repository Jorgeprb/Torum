import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  CalendarRange,
  Check,
  ChevronDown,
  Clock3,
  Coins,
  Database,
  Gauge,
  Layers3,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Target,
  Wrench,
} from "lucide-react";
import { useMemo, useState } from "react";

import type { TorumFieldDescriptor, TorumV1Configuration } from "../../../services/strategies";
import { StrategyField } from "../torum/StrategyField";
import type {
  SimulatorDrawingOption,
  SimulatorPreset,
  SimulatorRequestSettings,
  SimulatorSetupStep,
  SimulatorSymbol,
} from "./simulatorTypes";

type ParameterMode = "SIMPLE" | "ADVANCED";

interface StrategySimulatorSetupPanelProps {
  activeStep: SimulatorSetupStep;
  configuration: TorumV1Configuration | null;
  fromLocal: string;
  onApplyPreset: (preset: Exclude<SimulatorPreset, "CUSTOM">) => void;
  onClearDateRange: () => void;
  onClearParamOverride: (key?: string) => void;
  onParamOverride: (key: string, value: unknown) => void;
  onReloadDrawings: () => void;
  onRequestChange: <K extends keyof SimulatorRequestSettings>(key: K, value: SimulatorRequestSettings[K]) => void;
  onSelectAll: (kind: "ZONE" | "SUPPORT", selected: boolean) => void;
  onStepChange: (step: SimulatorSetupStep) => void;
  onSymbolChange: (symbol: SimulatorSymbol) => void;
  onToggleSelected: (kind: "ZONE" | "SUPPORT", id: string) => void;
  overrideCount: number;
  paramOverrides: Record<string, unknown>;
  preset: SimulatorPreset;
  publishedParams: Record<string, unknown>;
  request: SimulatorRequestSettings;
  running: boolean;
  selectedSupportIds: Set<string>;
  selectedZoneIds: Set<string>;
  setFromLocal: (value: string) => void;
  setToLocal: (value: string) => void;
  supports: SimulatorDrawingOption[];
  symbol: SimulatorSymbol;
  toLocal: string;
  zones: SimulatorDrawingOption[];
}

const steps: Array<{ id: SimulatorSetupStep; label: string; hint: string; icon: typeof Database }> = [
  { id: "MARKET", label: "Mercado", hint: "Activo y periodo", icon: Database },
  { id: "FILTERS", label: "Condiciones", hint: "Filtros y dibujos", icon: Layers3 },
  { id: "PARAMETERS", label: "Parámetros", hint: "Reglas Torum V1", icon: SlidersHorizontal },
  { id: "EXECUTION", label: "Ejecución", hint: "Costes y depuración", icon: Wrench },
];

const quickParameterKeys = new Set(["pullback_entry_min_pct", "take_profit_percent", "suggested_volume", "max_equivalent_positions"]);

const presetCopy: Record<Exclude<SimulatorPreset, "CUSTOM">, { title: string; detail: string; badge: string }> = {
  REALISTIC: { title: "Realista", detail: "Replica los filtros publicados y usa ejecución en la siguiente apertura.", badge: "Recomendado" },
  CONSERVATIVE: { title: "Conservador", detail: "Añade spread, slippage y comisión para evitar resultados idealizados.", badge: "Costes altos" },
  TECHNICAL: { title: "Solo técnico", detail: "Aísla la lógica de entrada desactivando contexto, riesgo y capacidad ATH.", badge: "Diagnóstico" },
};

function numericValue(value: unknown, fallback: number): number | string {
  return typeof value === "number" || typeof value === "string" ? value : fallback;
}

function ToggleCard({
  checked,
  description,
  disabled,
  label,
  onChange,
}: {
  checked: boolean;
  description: string;
  disabled?: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className={checked ? "strategy-sim-condition-card is-active" : "strategy-sim-condition-card"}>
      <span className="strategy-sim-condition-card__check">{checked ? <Check size={14} /> : null}</span>
      <span><strong>{label}</strong><small>{description}</small></span>
      <input checked={checked} disabled={disabled} type="checkbox" onChange={(event) => onChange(event.target.checked)} />
    </label>
  );
}

function StepActions({
  activeStep,
  onStepChange,
}: {
  activeStep: SimulatorSetupStep;
  onStepChange: (step: SimulatorSetupStep) => void;
}) {
  const index = steps.findIndex((step) => step.id === activeStep);
  return (
    <div className="strategy-sim-step-actions">
      <button disabled={index <= 0} type="button" onClick={() => onStepChange(steps[index - 1].id)}><ArrowLeft size={15} /> Anterior</button>
      <span>Paso {index + 1} de {steps.length}</span>
      <button disabled={index >= steps.length - 1} type="button" onClick={() => onStepChange(steps[index + 1].id)}>Siguiente <ArrowRight size={15} /></button>
    </div>
  );
}

export function StrategySimulatorSetupPanel({
  activeStep,
  configuration,
  fromLocal,
  onApplyPreset,
  onClearDateRange,
  onClearParamOverride,
  onParamOverride,
  onReloadDrawings,
  onRequestChange,
  onSelectAll,
  onStepChange,
  onSymbolChange,
  onToggleSelected,
  overrideCount,
  paramOverrides,
  preset,
  publishedParams,
  request,
  running,
  selectedSupportIds,
  selectedZoneIds,
  setFromLocal,
  setToLocal,
  supports,
  symbol,
  toLocal,
  zones,
}: StrategySimulatorSetupPanelProps) {
  const [parameterMode, setParameterMode] = useState<ParameterMode>("SIMPLE");
  const [parameterQuery, setParameterQuery] = useState("");

  const groupedParameterFields = useMemo(() => {
    if (!configuration) return [];
    const query = parameterQuery.trim().toLowerCase();
    return configuration.schema.groups
      .slice()
      .sort((a, b) => a.order - b.order)
      .map((group) => ({
        group,
        fields: configuration.schema.fields.filter((field) => {
          if (field.group !== group.key) return false;
          if (parameterMode === "SIMPLE" && field.advanced) return false;
          if (!query) return true;
          return `${field.label} ${field.description} ${field.key}`.toLowerCase().includes(query);
        }),
      }))
      .filter((item) => item.fields.length > 0);
  }, [configuration, parameterMode, parameterQuery]);

  return (
    <aside className="strategy-simulator-controls">
      <nav className="strategy-sim-stepper" aria-label="Configuración de la simulación">
        {steps.map((step, index) => {
          const Icon = step.icon;
          return (
            <button className={activeStep === step.id ? "is-active" : ""} key={step.id} type="button" onClick={() => onStepChange(step.id)}>
              <span>{index + 1}</span>
              <Icon size={16} />
              <strong>{step.label}</strong>
              <small>{step.hint}</small>
            </button>
          );
        })}
      </nav>

      <div className="strategy-sim-step-panel">
        {activeStep === "MARKET" ? (
          <>
            <header className="strategy-sim-step-heading">
              <div><Target size={19} /><span><strong>Mercado y muestra histórica</strong><small>Define qué activo y qué tramo de datos se va a reproducir.</small></span></div>
            </header>

            <div className="strategy-sim-symbol-picker" role="radiogroup" aria-label="Activo simulado">
              {(["XAUUSD", "XAUEUR"] as SimulatorSymbol[]).map((item) => (
                <button className={symbol === item ? "is-active" : ""} disabled={running} key={item} type="button" onClick={() => onSymbolChange(item)}>
                  <Coins size={18} /><span><strong>{item}</strong><small>{item === "XAUUSD" ? "Oro frente a dólar" : "Oro frente a euro"}</small></span>{symbol === item ? <Check size={16} /> : null}
                </button>
              ))}
            </div>

            <div className="strategy-sim-form-grid">
              <label className="strategy-flow-field">
                <span>Velas M5 máximas</span>
                <select value={request.candle_limit} onChange={(event) => onRequestChange("candle_limit", Number(event.target.value))}>
                  <option value={500}>500 · prueba rápida</option>
                  <option value={1500}>1.500 · aproximadamente 1 semana</option>
                  <option value={3000}>3.000 · aproximadamente 2 semanas</option>
                  <option value={5000}>5.000 · análisis amplio</option>
                  <option value={10000}>10.000 · máximo detalle</option>
                </select>
                <small>El límite se aplica también cuando eliges fechas.</small>
              </label>
              <label className="strategy-flow-field">
                <span>Balance inicial</span>
                <input inputMode="decimal" min="1" step="100" type="number" value={request.initial_balance} onChange={(event) => onRequestChange("initial_balance", Number(event.target.value))} />
                <small>Se usa para calcular equity, exposición y drawdown.</small>
              </label>
            </div>

            <section className="strategy-sim-subsection">
              <div className="strategy-sim-subsection__title"><CalendarRange size={17} /><span><strong>Rango de fechas opcional</strong><small>Vacío = últimas velas disponibles en la base de datos.</small></span></div>
              <div className="strategy-sim-date-grid">
                <label className="strategy-flow-field"><span>Desde</span><input type="datetime-local" value={fromLocal} onChange={(event) => setFromLocal(event.target.value)} /></label>
                <label className="strategy-flow-field"><span>Hasta</span><input type="datetime-local" value={toLocal} onChange={(event) => setToLocal(event.target.value)} /></label>
              </div>
              {fromLocal || toLocal ? <button className="toolbar-action" type="button" onClick={onClearDateRange}><CalendarRange size={15} /> Usar últimas velas</button> : null}
            </section>

            <section className="strategy-sim-subsection">
              <div className="strategy-sim-subsection__title"><Gauge size={17} /><span><strong>Perfil de simulación</strong><small>Empieza con uno y personaliza después cualquier ajuste.</small></span></div>
              <div className="strategy-sim-preset-cards">
                {(Object.keys(presetCopy) as Array<Exclude<SimulatorPreset, "CUSTOM">>).map((item) => (
                  <button className={preset === item ? "is-active" : ""} key={item} type="button" onClick={() => onApplyPreset(item)}>
                    <span><strong>{presetCopy[item].title}</strong><b>{presetCopy[item].badge}</b></span>
                    <small>{presetCopy[item].detail}</small>
                  </button>
                ))}
              </div>
              {preset === "CUSTOM" ? <div className="strategy-sim-custom-notice"><SlidersHorizontal size={15} /> Escenario personalizado: has modificado uno o más valores del perfil.</div> : null}
            </section>
          </>
        ) : null}

        {activeStep === "FILTERS" ? (
          <>
            <header className="strategy-sim-step-heading">
              <div><Layers3 size={19} /><span><strong>Condiciones incluidas</strong><small>Activa solo las capas que deseas validar en esta ejecución.</small></span></div>
            </header>

            <div className="strategy-sim-condition-grid">
              <ToggleCard checked={request.use_session} description="Respeta el horario operativo de Torum." label="Horario" onChange={(value) => onRequestChange("use_session", value)} />
              <ToggleCard checked={request.use_unlock} description="Reconstruye el desbloqueo H2/H3 de cada jornada." label="Desbloqueo H2/H3" onChange={(value) => onRequestChange("use_unlock", value)} />
              <ToggleCard checked={request.use_news} description="Descarta señales dentro de zonas históricas de noticias." label="Noticias" onChange={(value) => onRequestChange("use_news", value)} />
              <ToggleCard checked={request.use_dxy} description="Aplica la fortaleza diaria DXY y su SMA." label="Fortaleza DXY" onChange={(value) => onRequestChange("use_dxy", value)} />
              <ToggleCard checked={request.use_ath_capacity} description="Limita la capacidad según la zona ATH." label="Capacidad por ATH" onChange={(value) => onRequestChange("use_ath_capacity", value)} />
              <ToggleCard checked={request.use_risk} description="Simula límites de riesgo agregado y exposición." label="Riesgo agregado" onChange={(value) => onRequestChange("use_risk", value)} />
            </div>

            <section className="strategy-sim-drawing-section">
              <header>
                <div><BarChart3 size={18} /><span><strong>Regiones de operativa Torum</strong><small>Se cargan desde los rectángulos marcados para Torum en el gráfico de {symbol}.</small></span></div>
                <label className="strategy-sim-master-switch"><input checked={request.use_operation_zones} type="checkbox" onChange={(event) => onRequestChange("use_operation_zones", event.target.checked)} /><span /></label>
              </header>
              {request.use_operation_zones ? (
                <>
                  <div className="strategy-sim-selection-toolbar"><span>{selectedZoneIds.size} de {zones.length} seleccionadas</span><button type="button" onClick={() => onSelectAll("ZONE", true)}>Todas</button><button type="button" onClick={() => onSelectAll("ZONE", false)}>Ninguna</button><button type="button" onClick={onReloadDrawings}><RefreshCw size={14} /> Recargar</button></div>
                  <div className="strategy-sim-drawing-grid">
                    {zones.length ? zones.map((zone) => (
                      <label className={selectedZoneIds.has(zone.id) ? "is-selected" : ""} key={zone.id}><input checked={selectedZoneIds.has(zone.id)} type="checkbox" onChange={() => onToggleSelected("ZONE", zone.id)} /><span><strong>{zone.label}</strong><small>ID {zone.id.slice(0, 8)}</small></span><Check size={15} /></label>
                    )) : <div className="strategy-sim-drawing-empty"><BarChart3 size={23} /><strong>No hay regiones Torum activas</strong><small>Dibuja una región en el gráfico y activa «Usar como región Torum».</small><button type="button" onClick={() => { window.location.hash = "/chart"; }}>Abrir gráfico</button></div>}
                  </div>
                </>
              ) : <p className="strategy-sim-disabled-copy">El motor ignorará la pertenencia del pullback a regiones de operativa.</p>}
            </section>

            <section className="strategy-sim-drawing-section">
              <header>
                <div><ShieldCheck size={18} /><span><strong>Soportes S1 / S2 / S3</strong><small>Controlan la clasificación del soporte y el multiplicador aplicado.</small></span></div>
                <label className="strategy-sim-master-switch"><input checked={request.use_supports} type="checkbox" onChange={(event) => onRequestChange("use_supports", event.target.checked)} /><span /></label>
              </header>
              {request.use_supports ? (
                <>
                  <div className="strategy-sim-selection-toolbar"><span>{selectedSupportIds.size} de {supports.length} seleccionados</span><button type="button" onClick={() => onSelectAll("SUPPORT", true)}>Todos</button><button type="button" onClick={() => onSelectAll("SUPPORT", false)}>Ninguno</button><button type="button" onClick={onReloadDrawings}><RefreshCw size={14} /> Recargar</button></div>
                  <div className="strategy-sim-drawing-grid">
                    {supports.length ? supports.map((support) => (
                      <label className={selectedSupportIds.has(support.id) ? `is-selected support-s${support.level ?? 1}` : ""} key={support.id}><input checked={selectedSupportIds.has(support.id)} type="checkbox" onChange={() => onToggleSelected("SUPPORT", support.id)} /><span><strong>{support.label}</strong><small>Soporte de nivel S{support.level ?? "—"}</small></span><Check size={15} /></label>
                    )) : <div className="strategy-sim-drawing-empty"><ShieldCheck size={23} /><strong>No hay soportes configurados</strong><small>Crea líneas horizontales y asígnales nivel S1, S2 o S3.</small><button type="button" onClick={() => { window.location.hash = "/chart"; }}>Abrir gráfico</button></div>}
                  </div>
                </>
              ) : <p className="strategy-sim-disabled-copy">Las entradas no requerirán soporte y usarán el multiplicador técnico base.</p>}
            </section>
          </>
        ) : null}

        {activeStep === "PARAMETERS" ? (
          <>
            <header className="strategy-sim-step-heading">
              <div><SlidersHorizontal size={19} /><span><strong>Parámetros temporales de Torum V1</strong><small>Solo afectan a esta simulación; la estrategia publicada no cambia.</small></span></div>
              {overrideCount ? <button className="toolbar-action" type="button" onClick={() => onClearParamOverride()}>{overrideCount} cambios · Restaurar</button> : null}
            </header>

            <section className="strategy-sim-quick-params">
              <label className="strategy-flow-field"><span>Pullback mínimo · %</span><input inputMode="decimal" min="0" step="0.01" type="number" value={numericValue(paramOverrides.pullback_entry_min_pct ?? publishedParams.pullback_entry_min_pct, 0.2)} onChange={(event) => onParamOverride("pullback_entry_min_pct", event.target.value === "" ? "" : Number(event.target.value))} /><small>Mínimo necesario para habilitar el setup.</small></label>
              <label className="strategy-flow-field"><span>Take profit · %</span><input inputMode="decimal" min="0.001" step="0.001" type="number" value={numericValue(paramOverrides.take_profit_percent ?? publishedParams.take_profit_percent, 0.09)} onChange={(event) => onParamOverride("take_profit_percent", event.target.value === "" ? "" : Number(event.target.value))} /><small>Objetivo calculado desde el precio de entrada.</small></label>
              <label className="strategy-flow-field"><span>Lotaje base</span><input inputMode="decimal" min="0.01" step="0.01" type="number" value={numericValue(paramOverrides.suggested_volume ?? publishedParams.suggested_volume, 0.01)} onChange={(event) => onParamOverride("suggested_volume", event.target.value === "" ? "" : Number(event.target.value))} /><small>Antes de multiplicadores por soporte y contexto.</small></label>
              <label className="strategy-flow-field"><span>Máx. equivalentes</span><input min="1" max="10" step="1" type="number" value={numericValue(paramOverrides.max_equivalent_positions ?? publishedParams.max_equivalent_positions, 3)} onChange={(event) => onParamOverride("max_equivalent_positions", event.target.value === "" ? "" : Number(event.target.value))} /><small>Límite de posiciones simultáneas equivalentes.</small></label>
            </section>

            <section className="strategy-sim-parameter-editor">
              <div className="strategy-sim-parameter-tools">
                <label><Search size={15} /><input placeholder="Buscar por nombre, explicación o clave…" value={parameterQuery} onChange={(event) => setParameterQuery(event.target.value)} /></label>
                <div><button className={parameterMode === "SIMPLE" ? "is-active" : ""} type="button" onClick={() => setParameterMode("SIMPLE")}>Esenciales</button><button className={parameterMode === "ADVANCED" ? "is-active" : ""} type="button" onClick={() => setParameterMode("ADVANCED")}>Todos</button></div>
              </div>
              {groupedParameterFields.map(({ group, fields }) => (
                <details className="strategy-sim-parameter-group" key={group.key} open={Boolean(parameterQuery)}>
                  <summary><span><strong>{group.label}</strong><small>{group.description}</small></span><b>{fields.length}</b><ChevronDown size={16} /></summary>
                  <div>{fields.map((field: TorumFieldDescriptor) => (
                    <div className={quickParameterKeys.has(field.key) ? "strategy-sim-param is-quick" : "strategy-sim-param"} key={field.key}>
                      <StrategyField descriptor={field} value={field.key in paramOverrides ? paramOverrides[field.key] : publishedParams[field.key]} onChange={(value) => onParamOverride(field.key, value)} />
                      {field.key in paramOverrides ? <button type="button" onClick={() => onClearParamOverride(field.key)}>Heredar publicado</button> : null}
                    </div>
                  ))}</div>
                </details>
              ))}
              {!configuration ? <p className="strategy-sim-loading-copy"><RefreshCw className="is-spinning" size={15} /> Cargando esquema de la estrategia…</p> : null}
              {configuration && groupedParameterFields.length === 0 ? <p>No hay parámetros que coincidan con la búsqueda.</p> : null}
            </section>
          </>
        ) : null}

        {activeStep === "EXECUTION" ? (
          <>
            <header className="strategy-sim-step-heading">
              <div><Wrench size={19} /><span><strong>Modelo de ejecución y depuración</strong><small>Define cuándo entra, qué costes se descuentan y cuánto detalle se registra.</small></span></div>
            </header>

            <section className="strategy-sim-subsection">
              <div className="strategy-sim-subsection__title"><Clock3 size={17} /><span><strong>Momento de entrada</strong><small>La apertura siguiente evita utilizar información que aún no existía al cerrar la vela de confirmación.</small></span></div>
              <div className="strategy-sim-entry-models">
                <label className={request.entry_model === "NEXT_OPEN" ? "is-active" : ""}><input checked={request.entry_model === "NEXT_OPEN"} name="entry-model" type="radio" onChange={() => onRequestChange("entry_model", "NEXT_OPEN")} /><span><strong>Apertura de la vela siguiente</strong><small>Recomendado y más realista. Añade spread y slippage a la ejecución.</small></span><b>REALISTA</b></label>
                <label className={request.entry_model === "CONFIRMATION_CLOSE" ? "is-active" : ""}><input checked={request.entry_model === "CONFIRMATION_CLOSE"} name="entry-model" type="radio" onChange={() => onRequestChange("entry_model", "CONFIRMATION_CLOSE")} /><span><strong>Cierre de confirmación</strong><small>Modelo idealizado para estudiar únicamente la señal técnica.</small></span><b>IDEAL</b></label>
              </div>
            </section>

            <section className="strategy-sim-subsection">
              <div className="strategy-sim-subsection__title"><Coins size={17} /><span><strong>Costes simulados</strong><small>Se expresan en puntos o por lote según corresponda.</small></span></div>
              <div className="strategy-sim-form-grid strategy-sim-form-grid--three">
                <label className="strategy-flow-field"><span>Spread · puntos</span><input min="0" step="0.1" type="number" value={request.spread_points} onChange={(event) => onRequestChange("spread_points", Number(event.target.value))} /></label>
                <label className="strategy-flow-field"><span>Slippage · puntos</span><input min="0" step="0.1" type="number" value={request.slippage_points} onChange={(event) => onRequestChange("slippage_points", Number(event.target.value))} /></label>
                <label className="strategy-flow-field"><span>Comisión por lote</span><input min="0" step="0.1" type="number" value={request.commission_per_lot} onChange={(event) => onRequestChange("commission_per_lot", Number(event.target.value))} /></label>
              </div>
            </section>

            <section className="strategy-sim-subsection">
              <div className="strategy-sim-subsection__title"><Settings2 size={17} /><span><strong>Nivel de depuración</strong><small>Cuanto mayor sea el detalle, más fácil será explicar una entrada o descarte.</small></span></div>
              <div className="strategy-sim-debug-levels">
                <label className={request.debug_level === "SUMMARY" ? "is-active" : ""}><input checked={request.debug_level === "SUMMARY"} name="debug-level" type="radio" onChange={() => onRequestChange("debug_level", "SUMMARY")} /><strong>Resumen</strong><small>Solo entradas y salidas.</small></label>
                <label className={request.debug_level === "SIGNALS" ? "is-active" : ""}><input checked={request.debug_level === "SIGNALS"} name="debug-level" type="radio" onChange={() => onRequestChange("debug_level", "SIGNALS")} /><strong>Señales</strong><small>Entradas, salidas y bloqueos relevantes.</small></label>
                <label className={request.debug_level === "FULL" ? "is-active" : ""}><input checked={request.debug_level === "FULL"} name="debug-level" type="radio" onChange={() => onRequestChange("debug_level", "FULL")} /><strong>Completa</strong><small>Cada vela evaluada; úsala para tramos pequeños.</small></label>
              </div>
              <div className="strategy-sim-form-grid">
                <label className="strategy-flow-field"><span>Máx. eventos de depuración</span><input min="50" max="10000" step="50" type="number" value={request.max_debug_events} onChange={(event) => onRequestChange("max_debug_events", Number(event.target.value))} /><small>La traza avisa si se alcanza el límite.</small></label>
                <ToggleCard checked={request.close_open_trades_at_end} description="Valora las operaciones abiertas con el último cierre disponible." label="Cerrar operaciones al terminar" onChange={(value) => onRequestChange("close_open_trades_at_end", value)} />
              </div>
            </section>
          </>
        ) : null}

        <StepActions activeStep={activeStep} onStepChange={onStepChange} />
      </div>
    </aside>
  );
}
