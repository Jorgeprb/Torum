import { ChevronDown, Info, Power, X } from "lucide-react";
import { type KeyboardEvent, useEffect, useMemo, useState } from "react";

import type { Timeframe } from "../../services/market";
import {
  type StrategyConfig,
  type StrategyDefinition,
  type StrategySettings,
  createStrategyConfig,
  getStrategies,
  getStrategyConfigs,
  getStrategySettings,
  patchStrategyConfig,
  registerDefaultStrategies,
} from "../../services/strategies";

const TORUM_V1_KEY = "torum_v1";
const torumSymbols = ["XAUEUR", "XAUUSD"];

interface StrategyPanelProps {
  symbols: string[];
  timeframes: Timeframe[];
  onChanged?: () => void;
}

type NumericParamKey =
  | "pullback_min_pct"
  | "pullback_entry_min_pct"
  | "pullback_max_count"
  | "pullback_lookback_bars"
  | "pullback_recovery_pct"
  | "pullback_end_confirmation_bars"
  | "pullback_min_bars_between"
  | "pullback_swing_confirm_bars"
  | "pullback_min_bearish_candles"
  | "pullback_min_lower_close_candles"
  | "pullback_label_decimals"
  | "pullback_line_width"
  | "pullback_opacity"
  | "usd_sma_period"
  | "usd_neutral_band_points"
  | "usd_strong_drop_lookback_days"
  | "usd_strong_drop_min_pct";

interface NumericParamConfig {
  key: NumericParamKey;
  label: string;
  help: string;
  min: number;
  max?: number;
  step: string;
  integer?: boolean;
  decimals?: number;
}

const numericParams: NumericParamConfig[] = [
  { key: "pullback_min_pct", label: "PB min %", help: "Pullback minimo para pintar/calcular. 0 muestra todos.", min: 0, step: "0.01", decimals: 3 },
  { key: "pullback_entry_min_pct", label: "PB entrada %", help: "Pullback minimo para que el bot pueda entrar. No afecta necesariamente al PB visual.", min: 0.01, max: 20, step: "0.01", decimals: 3 },
  { key: "pullback_max_count", label: "Max PB", help: "Cantidad maxima de pullbacks recientes a mostrar.", min: 1, max: 50, step: "1", integer: true },
  { key: "pullback_lookback_bars", label: "Lookback M5", help: "Velas usadas para buscar estructura/pullback.", min: 2, max: 300, step: "1", integer: true },
  { key: "pullback_recovery_pct", label: "Recuperacion %", help: "Rebote necesario desde el minimo para cerrar el pullback.", min: 0, max: 20, step: "0.01", decimals: 3 },
  { key: "pullback_end_confirmation_bars", label: "Velas confirma", help: "Numero de velas que confirman recuperacion.", min: 1, max: 20, step: "1", integer: true },
  { key: "pullback_min_bars_between", label: "Separacion velas", help: "Distancia minima entre pullbacks.", min: 0, max: 100, step: "1", integer: true },
  { key: "pullback_swing_confirm_bars", label: "Confirmacion maximo", help: "Velas usadas para confirmar que el maximo es real antes de anclar el pullback.", min: 0, max: 10, step: "1", integer: true },
  { key: "pullback_min_bearish_candles", label: "Min velas bajistas", help: "Exige velas rojas antes de aceptar el pullback.", min: 0, max: 10, step: "1", integer: true },
  { key: "pullback_min_lower_close_candles", label: "Min lower-close", help: "Exige cierres descendentes desde el maximo.", min: 0, max: 10, step: "1", integer: true },
  { key: "pullback_label_decimals", label: "Decimales etiqueta", help: "Decimales del porcentaje mostrado.", min: 0, max: 6, step: "1", integer: true },
  { key: "pullback_line_width", label: "Ancho linea", help: "Grosor visual.", min: 1, max: 8, step: "1", integer: true },
  { key: "pullback_opacity", label: "Opacidad", help: "Transparencia visual.", min: 0.1, max: 1, step: "0.05", decimals: 2 },
  { key: "usd_sma_period", label: "SMA DXY", help: "Periodo diario usado para la media del DXY sintetico.", min: 5, max: 200, step: "1", integer: true },
  { key: "usd_neutral_band_points", label: "Banda neutra DXY", help: "Distancia entre DXY y SMA donde el dolar se considera neutro.", min: 0, max: 5, step: "0.01", decimals: 3 },
  { key: "usd_strong_drop_lookback_days", label: "Dias caida fuerte", help: "Dias usados para medir caida fuerte del DXY.", min: 1, max: 30, step: "1", integer: true },
  { key: "usd_strong_drop_min_pct", label: "Caida fuerte %", help: "Caida minima para permitir compras aunque DXY este sobre SMA30.", min: 0, max: 10, step: "0.01", decimals: 3 },
];

const booleanParamHelps: Record<string, string> = {
  enable_operation_zones: "Permite activar rectangulos como zona operativa.",
  show_pullback_debug: "Pinta pullbacks calculados en el grafico.",
  pullback_enabled: "Activa el calculo de pullbacks.",
  pullback_live_update_enabled: "Actualiza el pullback vivo con ticks.",
  pullback_use_wicks: "Usa high/low en vez de close.",
  pullback_use_close_confirmation: "Exige vela de recuperacion alcista.",
  pullback_show_labels: "Muestra etiqueta PB con porcentaje.",
  pullback_show_only_live: "Muestra solo el pullback activo.",
  pullback_allow_peak_extension: "Si aparece un high mayor dentro del mismo tramo, mueve el inicio del PB a ese maximo.",
  pullback_require_bearish_leg: "Evita marcar como pullback una vela verde con mucho rango.",
  pullback_disallow_same_candle_peak_low: "Impide usar high y low de la misma vela como pullback.",
  pullback_impulse_green_filter_enabled: "Bloquea PB falsos en velas alcistas de impulso.",
  require_zone: "Bot solo opera dentro de zona operativa.",
  one_position_per_symbol: "Limita entradas simultaneas del bot.",
  usd_strength_filter_enabled: "DXY > SMA30 bloquea compras automaticas. Solo afecta al BOT.",
  usd_allow_when_neutral: "Permite operar si DXY esta cerca de SMA30.",
  usd_strong_drop_override_enabled: "Si DXY cae fuerte, permite operar aunque este sobre SMA30.",
  usd_strong_drop_require_bearish_close: "Exige vela diaria bajista para activar la caida fuerte.",
  usd_strength_strict: "Si DXY es desconocido, bloquea el BOT.",
};

function defaultTorumParams(symbol: string): Record<string, unknown> {
  return {
    enabled: true,
    use_news: true,
    timeframe: "H2",
    session_start: symbol === "XAUEUR" ? "09:00" : "15:30",
    session_end: symbol === "XAUEUR" ? "15:00" : "21:00",
    enable_operation_zones: true,
    entry_timeframe: "M5",
    pullback_enabled: true,
    pullback_max_count: 10,
    pullback_min_pct: 0,
    pullback_threshold_pct: 0,
    pullback_entry_min_pct: 0.20,
    pullback_lookback_bars: 12,
    pullback_swing_confirm_bars: 1,
    pullback_allow_peak_extension: true,
    pullback_require_bearish_leg: true,
    pullback_min_bearish_candles: 1,
    pullback_min_lower_close_candles: 1,
    pullback_disallow_same_candle_peak_low: true,
    pullback_impulse_green_filter_enabled: true,
    pullback_recovery_pct: 0.10,
    pullback_end_confirmation_bars: 1,
    pullback_min_bars_between: 0,
    pullback_use_wicks: true,
    pullback_use_close_confirmation: true,
    pullback_live_update_enabled: true,
    pullback_show_labels: true,
    pullback_show_only_live: false,
    pullback_label_decimals: 2,
    pullback_line_width: 2,
    pullback_opacity: 0.95,
    show_pullback_debug: false,
    require_zone: true,
    one_position_per_symbol: false,
    usd_strength_filter_enabled: true,
    usd_strength_apply_to_symbols: ["XAUUSD", "XAUEUR"],
    usd_strength_mode: "only_operate_when_weak",
    usd_sma_period: 30,
    usd_neutral_band_points: 0.10,
    usd_allow_when_neutral: false,
    usd_strong_drop_override_enabled: true,
    usd_strong_drop_lookback_days: 3,
    usd_strong_drop_min_pct: 0.45,
    usd_strong_drop_require_bearish_close: true,
    usd_strength_strict: false
  };
}

function fixedTorumParams(symbol: string, current: Record<string, unknown> | undefined, enabled: boolean): Record<string, unknown> {
  return {
    ...defaultTorumParams(symbol),
    ...(current ?? {}),
    enabled,
    entry_timeframe: "M5",
    timeframe: "H2",
    session_start: symbol === "XAUEUR" ? "09:00" : "15:30",
    session_end: symbol === "XAUEUR" ? "15:00" : "21:00",
    pullback_threshold_pct: current?.pullback_threshold_pct ?? current?.pullback_min_pct ?? 0,
  };
}

function formatDraftValue(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : String(value ?? "");
}

function normalizeNumericValue(raw: string, config: NumericParamConfig): number | null {
  const normalized = raw.trim().replace(",", ".");
  if (normalized === "" || normalized === "." || normalized === "0.") return null;
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed)) return null;
  let value = config.integer ? Math.round(parsed) : parsed;
  value = Math.max(config.min, value);
  if (typeof config.max === "number") value = Math.min(config.max, value);
  return config.integer ? value : Number(value.toFixed(config.decimals ?? 4));
}

export function StrategyPanel({ symbols, timeframes, onChanged }: StrategyPanelProps) {
  void symbols;
  void timeframes;
  const [definitions, setDefinitions] = useState<StrategyDefinition[]>([]);
  const [configs, setConfigs] = useState<StrategyConfig[]>([]);
  const [settings, setSettings] = useState<StrategySettings | null>(null);
  const [torumExpanded, setTorumExpanded] = useState(false);
  const [torumInfoOpen, setTorumInfoOpen] = useState(false);
  const [draftParams, setDraftParams] = useState<Record<string, string>>({});
  const [activeDraftKey, setActiveDraftKey] = useState<string | null>(null);
  const [savingDraftKey, setSavingDraftKey] = useState<string | null>(null);

  const torumDefinition = useMemo(
    () => definitions.find((definition) => definition.key === TORUM_V1_KEY),
    [definitions]
  );
  const torumConfigs = useMemo(
    () => configs.filter((config) => config.strategy_key === TORUM_V1_KEY).sort((left, right) => left.id - right.id),
    [configs]
  );
  const torumEnabled = torumSymbols.every((symbol) => torumConfigs.some((config) => config.internal_symbol === symbol && config.enabled));
  const torumParams = useMemo(
    () => ({ ...defaultTorumParams("XAUUSD"), ...(torumConfigs[0]?.params_json ?? {}) }),
    [torumConfigs]
  );

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    if (activeDraftKey) return;
    setDraftParams((current) => {
      const next = { ...current };
      for (const config of numericParams) {
        next[config.key] = formatDraftValue(torumParams[config.key]);
      }
      return next;
    });
  }, [activeDraftKey, torumParams]);

  async function refresh() {
    let [definitionResponse, configResponse, settingsResponse] = await Promise.all([
      getStrategies(),
      getStrategyConfigs(),
      getStrategySettings(),
    ]);
    if (!definitionResponse.some((definition) => definition.key === TORUM_V1_KEY)) {
      definitionResponse = await registerDefaultStrategies();
      configResponse = await getStrategyConfigs();
      settingsResponse = await getStrategySettings();
    }
    setDefinitions(definitionResponse);
    setConfigs(configResponse);
    setSettings(settingsResponse);
  }

  async function ensureTorumConfig(symbol: string, enabled: boolean): Promise<StrategyConfig> {
    const existing = torumConfigs.find((config) => config.internal_symbol === symbol);
    if (existing) {
      const updated = await patchStrategyConfig(existing.id, {
        enabled,
        timeframe: "H2",
        params_json: fixedTorumParams(symbol, existing.params_json, enabled)
      });
      setConfigs((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      return updated;
    }

    const created = await createStrategyConfig({
      strategy_key: TORUM_V1_KEY,
      internal_symbol: symbol,
      timeframe: "H2",
      enabled,
      mode: settings?.default_mode ?? "PAPER",
      params_json: fixedTorumParams(symbol, undefined, enabled)
    });
    setConfigs((current) => [...current, created]);
    return created;
  }

  function mergeUpdatedConfigs(updated: StrategyConfig[]) {
    setConfigs((current) => {
      const byId = new Map(current.map((config) => [config.id, config]));
      for (const config of updated) byId.set(config.id, config);
      return [...byId.values()].sort((left, right) => left.id - right.id);
    });
  }

  async function handleToggleTorum(nextEnabled: boolean) {
    try {
      const updated = await Promise.all(torumSymbols.map((symbol) => ensureTorumConfig(symbol, nextEnabled)));
      mergeUpdatedConfigs(updated);
      onChanged?.();
    } catch {
      // La UI queda igual si falla el backend.
    }
  }

  async function updateTorumParams(patch: Record<string, unknown>) {
    try {
      const readyConfigs = await Promise.all(torumSymbols.map((symbol) => ensureTorumConfig(symbol, torumEnabled)));
      const updated = await Promise.all(
        readyConfigs.map((config) =>
          patchStrategyConfig(config.id, {
            timeframe: "H2",
            params_json: {
              ...fixedTorumParams(config.internal_symbol, config.params_json, torumEnabled),
              ...patch
            }
          })
        )
      );
      mergeUpdatedConfigs(updated);
      onChanged?.();
    } catch {
      // Silencio simple. La card refresca en siguiente carga.
    }
  }

  async function commitNumericParam(config: NumericParamConfig) {
    const raw = draftParams[config.key] ?? "";
    const value = normalizeNumericValue(raw, config);
    setActiveDraftKey(null);
    if (value === null) {
      setDraftParams((current) => ({ ...current, [config.key]: formatDraftValue(torumParams[config.key]) }));
      return;
    }
    setSavingDraftKey(config.key);
    const patch: Record<string, unknown> = { [config.key]: value };
    if (config.key === "pullback_min_pct") patch.pullback_threshold_pct = value;
    try {
      await updateTorumParams(patch);
      setDraftParams((current) => ({ ...current, [config.key]: formatDraftValue(value) }));
    } finally {
      setSavingDraftKey(null);
    }
  }

  function handleNumericKeyDown(event: KeyboardEvent<HTMLInputElement>, config: NumericParamConfig) {
    if (event.key === "Enter") {
      event.currentTarget.blur();
      void commitNumericParam(config);
    }
  }

  const globalDisabled = settings && (!settings.strategies_enabled || !settings.strategy_live_enabled);

  return (
    <section className="strategy-workbench">
      <section className="table-panel strategy-card strategy-card--torum">
        <div className="strategy-card__header strategy-card__header--power">
          <button
            aria-expanded={torumExpanded}
            className="strategy-card__summary-trigger"
            type="button"
            onClick={() => setTorumExpanded((current) => !current)}
          >
            <ChevronDown
              className={torumExpanded ? "strategy-card__chevron strategy-card__chevron--open" : "strategy-card__chevron"}
              size={18}
            />
            <strong>{torumDefinition?.name ?? "Estrategia Torum V1.0"}</strong>
          </button>
          <button
            aria-label="Informacion Torum V1"
            className="strategy-info-button"
            type="button"
            onClick={() => setTorumInfoOpen(true)}
          >
            <Info size={17} />
          </button>
          <button
            aria-label={torumEnabled ? "Apagar estrategia Torum V1" : "Encender estrategia Torum V1"}
            aria-pressed={torumEnabled}
            className={torumEnabled ? "strategy-power-toggle strategy-power-toggle--on" : "strategy-power-toggle strategy-power-toggle--off"}
            type="button"
            onClick={() => void handleToggleTorum(!torumEnabled)}
          >
            <Power size={18} />
            <span>{torumEnabled ? "ON" : "OFF"}</span>
          </button>
        </div>
        {globalDisabled ? <p className="strategy-global-warning">Motor global apagado. El boton Torum solo cambia esta estrategia.</p> : null}
        {torumExpanded ? (
          <div className="strategy-card__body strategy-card__summary">
            <p>
              Bloquea o libera el BOT por activo segun horario, velas cerradas y noticias.
              El usuario manual siempre puede operar.
            </p>
            <div className="strategy-card__meta">
              <span>XAUEUR 09:00-15:00</span>
              <span>XAUUSD 15:30-21:00</span>
              <span>Noticias bloquean solo BOT</span>
            </div>
            <div className="strategy-torum-settings">
              {[
                ["enable_operation_zones", "Zonas operativas", torumParams.enable_operation_zones === true],
                ["show_pullback_debug", "Mostrar pullbacks M5 calculados", torumParams.show_pullback_debug === true],
                ["pullback_enabled", "Calcular pullbacks", torumParams.pullback_enabled !== false],
                ["pullback_live_update_enabled", "Actualizar en vivo", torumParams.pullback_live_update_enabled !== false],
                ["pullback_use_wicks", "Usar mechas", torumParams.pullback_use_wicks !== false],
                ["pullback_use_close_confirmation", "Confirmar con vela alcista", torumParams.pullback_use_close_confirmation !== false],
                ["pullback_show_labels", "Etiquetas PB", torumParams.pullback_show_labels !== false],
                ["pullback_show_only_live", "Solo PB vivo", torumParams.pullback_show_only_live === true],
                ["pullback_allow_peak_extension", "Permitir actualizar maximo", torumParams.pullback_allow_peak_extension !== false],
                ["pullback_require_bearish_leg", "Requerir tramo bajista", torumParams.pullback_require_bearish_leg !== false],
                ["pullback_disallow_same_candle_peak_low", "Evitar PB misma vela", torumParams.pullback_disallow_same_candle_peak_low !== false],
                ["pullback_impulse_green_filter_enabled", "Filtro impulso verde", torumParams.pullback_impulse_green_filter_enabled !== false],
                ["require_zone", "Requerir zona", torumParams.require_zone !== false],
                ["one_position_per_symbol", "Una posicion por activo", torumParams.one_position_per_symbol !== false],
                ["usd_strength_filter_enabled", "Filtro fortaleza USD", torumParams.usd_strength_filter_enabled !== false],
                ["usd_allow_when_neutral", "Permitir dolar neutro", torumParams.usd_allow_when_neutral === true],
                ["usd_strong_drop_override_enabled", "Permitir caida fuerte DXY", torumParams.usd_strong_drop_override_enabled !== false],
                ["usd_strong_drop_require_bearish_close", "DXY diario bajista", torumParams.usd_strong_drop_require_bearish_close !== false],
                ["usd_strength_strict", "Bloquear si DXY desconocido", torumParams.usd_strength_strict === true],
              ].map(([key, label, checked]) => (
                <label className="toggle-line strategy-param-line" key={String(key)} title={booleanParamHelps[String(key)]}>
                  <input
                    checked={Boolean(checked)}
                    type="checkbox"
                    onChange={(event) => void updateTorumParams({ [String(key)]: event.target.checked })}
                  />
                  <span>{String(label)}</span>
                  <small>{booleanParamHelps[String(key)]}</small>
                </label>
              ))}

              {numericParams.map((config) => (
                <label className="strategy-param-line" key={config.key} title={config.help}>
                  <span>{config.label}</span>
                  <input
                    inputMode={config.integer ? "numeric" : "decimal"}
                    max={config.max}
                    min={config.min}
                    step={config.step}
                    type="text"
                    value={draftParams[config.key] ?? formatDraftValue(torumParams[config.key])}
                    onBlur={() => void commitNumericParam(config)}
                    onChange={(event) => {
                      setActiveDraftKey(config.key);
                      setDraftParams((current) => ({ ...current, [config.key]: event.target.value }));
                    }}
                    onFocus={() => setActiveDraftKey(config.key)}
                    onKeyDown={(event) => handleNumericKeyDown(event, config)}
                  />
                  <small>{savingDraftKey === config.key ? "Guardando..." : config.help}</small>
                </label>
              ))}

              <label className="strategy-param-line">
                <span>Entrada</span>
                <input disabled value="M5" readOnly />
                <small>Timeframe usado por el bot para entrada.</small>
              </label>
            </div>
          </div>
        ) : null}
      </section>
      {torumInfoOpen ? (
        <div className="modal-backdrop strategy-info-backdrop" role="presentation" onMouseDown={() => setTorumInfoOpen(false)}>
          <section className="confirm-modal strategy-info-modal" role="dialog" aria-modal="true" aria-label="Resumen Estrategia Torum V1" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-title-row">
              <Info size={19} />
              <h2>Estrategia Torum V1.0</h2>
              <button className="mobile-icon-button strategy-info-close" type="button" aria-label="Cerrar" onClick={() => setTorumInfoOpen(false)}>
                <X size={18} />
              </button>
            </div>
            <div className="strategy-info-list">
              <p>Solo BOT. Usuario manual siempre puede operar.</p>
              <p>Solo BUY. Nunca SELL.</p>
              <p>XAUEUR opera 09:00-15:00 Europe/Madrid. XAUUSD opera 15:30-21:00.</p>
              <p>Desbloquea por velas cerradas 2H o 3H. Reset diario por activo.</p>
              <p>Noticias bloquean solo BOT durante ventana configurada. Luego vuelve estado previo.</p>
              <p>Entrada M5: pullback configurable, despues vela alcista cerrada.</p>
              <p>Compra solo dentro de rectangulo operativo activo si exigir zona esta activo.</p>
              <p>Soportes S1/S2/S3 aumentan agresividad si hay capacidad.</p>
              <p>Zonas ATH limitan BOT: roja bloquea, naranja 1, amarilla 2, verde 3 lotajes.</p>
              <p>Filtro USD: si DXY esta sobre SMA30, bloquea compras del BOT.</p>
              <p>Si DXY cae fuerte, puede permitir compras aunque este sobre SMA30.</p>
              <p>Riesgo BOT: perdida potencial 30% no puede superar 50% del balance.</p>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
