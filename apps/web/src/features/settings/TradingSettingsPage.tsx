import { useEffect, useState } from "react";
import { Bell, Clock3, Eye, Gauge, LineChart, Save, ScanEye, Settings2, TrendingUp } from "lucide-react";

import {
  type MT5OrderExecutionSettings,
  type TradingMode,
  type TradingSettings,
  type AthLevel,
  getAthLevels,
  getMT5OrderExecutionSettings,
  getTradingSettings,
  patchAthLevel,
  patchTradingSettings
} from "../../services/trading";
import {
  activatePushNotifications,
  currentPushPermission,
  getPushStatus,
  sendTestPushNotification,
  type PushStatus
} from "../alerts/pushNotifications";
import {
  type StrategyConfig,
  createStrategyConfig,
  getStrategyConfigs,
  getStrategySettings,
  patchStrategyConfig
} from "../../services/strategies";

const spyModeStorageKey = "torum.spyMode";
const showFutureNewsZonesStorageKey = "torum.showFutureNewsZones";
const autoExtendToFutureNewsStorageKey = "torum.autoExtendToFutureNews";
const futureNewsVisualsChangedEvent = "torum-future-news-visuals-changed";
const chartTimeModeStorageKey = "torum.chartTimeMode";
const chartManualBrokerUtcOffsetStorageKey = "torum.chartManualBrokerUtcOffset";
const chartManualLocalUtcOffsetStorageKey = "torum.chartManualLocalUtcOffset";
const chartTimeSettingsChangedEvent = "torum-chart-time-settings-changed";
const defaultChartBrokerTimeZone = "Etc/GMT-3";
const chartDisplayTimeZone = "Europe/Madrid";
const utcOffsetOptions = Array.from({ length: 27 }, (_, index) => index - 12);
const torumV1Key = "torum_v1";
const torumSymbols = ["XAUEUR", "XAUUSD"];
type ChartTimeMode = "auto" | "manual";

interface TradingSettingsPageProps {
  onChanged?: () => void;
}

function torumParams(symbol: string, current?: Record<string, unknown>, enabled = false, showPullbacks = false): Record<string, unknown> {
  return {
    enabled,
    use_news: current?.use_news ?? true,
    timeframe: "H2",
    session_start: symbol === "XAUEUR" ? "09:00" : "15:30",
    session_end: symbol === "XAUEUR" ? "15:00" : "21:00",
    enable_operation_zones: current?.enable_operation_zones ?? true,
    entry_timeframe: "M5",
    pullback_threshold_pct: current?.pullback_threshold_pct ?? 0.20,
    pullback_lookback_bars: current?.pullback_lookback_bars ?? 12,
    show_pullback_debug: showPullbacks,
    require_zone: current?.require_zone ?? true,
    one_position_per_symbol: current?.one_position_per_symbol ?? true
  };
}

function readSpyModePreference(): boolean {
  try {
    return window.localStorage.getItem(spyModeStorageKey) === "1";
  } catch {
    return false;
  }
}

function readDefaultTruePreference(key: string): boolean {
  try {
    return window.localStorage.getItem(key) !== "0";
  } catch {
    return true;
  }
}

function readChartTimeMode(): ChartTimeMode {
  try {
    return window.localStorage.getItem(chartTimeModeStorageKey) === "manual" ? "manual" : "auto";
  } catch {
    return "auto";
  }
}

function currentUtcOffsetHours(timeZone: string): number {
  const value = new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    hour12: false,
    hourCycle: "h23",
    timeZone
  }).format(new Date());
  const utcHour = new Date().getUTCHours();
  let offset = Number(value) - utcHour;

  if (offset > 12) {
    offset -= 24;
  }

  if (offset < -12) {
    offset += 24;
  }

  return offset;
}

function readStoredUtcOffset(key: string, fallback: number): number {
  try {
    const parsed = Number(window.localStorage.getItem(key));
    return Number.isInteger(parsed) && parsed >= -12 && parsed <= 14 ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function formatUtcOffset(offset: number): string {
  if (offset === 0) {
    return "UTC+0";
  }

  return `UTC${offset > 0 ? "+" : ""}${offset}`;
}

function saveChartTimePreference(key: string, value: string) {
  window.localStorage.setItem(key, value);
  window.dispatchEvent(new Event(chartTimeSettingsChangedEvent));
}

export function TradingSettingsPage({ onChanged }: TradingSettingsPageProps = {}) {
  const [settings, setSettings] = useState<TradingSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [pushStatus, setPushStatus] = useState<PushStatus>("permission-required");
  const [mt5Execution, setMt5Execution] = useState<MT5OrderExecutionSettings | null>(null);
  const [spyModeEnabled, setSpyModeEnabled] = useState(readSpyModePreference);
  const [showFutureNewsZones, setShowFutureNewsZones] = useState(() => readDefaultTruePreference(showFutureNewsZonesStorageKey));
  const [autoExtendToFutureNews, setAutoExtendToFutureNews] = useState(() => readDefaultTruePreference(autoExtendToFutureNewsStorageKey));
  const [showPullbackDebug, setShowPullbackDebug] = useState(false);
  const [athLevels, setAthLevels] = useState<AthLevel[]>([]);
  const [savingAthSymbol, setSavingAthSymbol] = useState<string | null>(null);
  const [chartTimeMode, setChartTimeMode] = useState(readChartTimeMode);
  const [chartBrokerUtcOffset, setChartBrokerUtcOffset] = useState(() =>
    readStoredUtcOffset(chartManualBrokerUtcOffsetStorageKey, currentUtcOffsetHours(import.meta.env.VITE_CHART_BROKER_TIME_ZONE || defaultChartBrokerTimeZone))
  );
  const [chartLocalUtcOffset, setChartLocalUtcOffset] = useState(() =>
    readStoredUtcOffset(chartManualLocalUtcOffsetStorageKey, currentUtcOffsetHours(chartDisplayTimeZone))
  );

  useEffect(() => {
    void getTradingSettings().then(setSettings).catch((error: unknown) => {
      setMessage(error instanceof Error ? error.message : "No se pudieron cargar los ajustes");
    });
    void refreshMt5Execution();
    void getPushStatus().then(setPushStatus);
    void refreshPullbackDebug();
    void refreshAthLevels();
  }, []);

  function update<K extends keyof TradingSettings>(key: K, value: TradingSettings[K]) {
    setSettings((current) => (current ? { ...current, [key]: value } : current));
  }

  function updateSpyMode(enabled: boolean) {
    setSpyModeEnabled(enabled);
    try {
      window.localStorage.setItem(spyModeStorageKey, enabled ? "1" : "0");
      window.dispatchEvent(new Event("torum-spy-mode-changed"));
    } catch {
      setMessage("No se pudo guardar modo espia");
    }
  }

  function updateFutureNewsVisual(key: string, enabled: boolean) {
    if (key === showFutureNewsZonesStorageKey) {
      setShowFutureNewsZones(enabled);
    } else {
      setAutoExtendToFutureNews(enabled);
    }

    try {
      window.localStorage.setItem(key, enabled ? "1" : "0");
      window.dispatchEvent(new Event(futureNewsVisualsChangedEvent));
    } catch {
      setMessage("No se pudo guardar visual de noticias");
    }
  }

  function updateChartTimeMode(mode: ChartTimeMode) {
    setChartTimeMode(mode);
    try {
      saveChartTimePreference(chartTimeModeStorageKey, mode);
      setMessage("Horario de grafico guardado");
    } catch {
      setMessage("No se pudo guardar horario de grafico");
    }
  }

  function updateChartUtcOffset(key: string, value: number) {
    const safeValue = Math.max(-12, Math.min(14, Math.floor(value)));

    if (key === chartManualBrokerUtcOffsetStorageKey) {
      setChartBrokerUtcOffset(safeValue);
    } else {
      setChartLocalUtcOffset(safeValue);
    }

    try {
      saveChartTimePreference(key, String(safeValue));
      setMessage("Horario de grafico guardado");
    } catch {
      setMessage("No se pudo guardar horario de grafico");
    }
  }

  async function refreshPullbackDebug() {
    try {
      const configs = await getStrategyConfigs();
      setShowPullbackDebug(
        configs.some((config) => config.strategy_key === torumV1Key && config.params_json?.show_pullback_debug === true)
      );
    } catch {
      setShowPullbackDebug(false);
    }
  }

  async function refreshAthLevels() {
    try {
      setAthLevels(await getAthLevels());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo cargar ATH");
    }
  }

  function updateAth(symbol: string, patch: Partial<AthLevel>) {
    setAthLevels((current) => {
      if (current.some((level) => level.internal_symbol === symbol)) {
        return current.map((level) => (level.internal_symbol === symbol ? { ...level, ...patch } : level));
      }
      return [
        ...current,
        {
          internal_symbol: symbol,
          ath_price: null,
          mode: "auto",
          source: "candles",
          calculated_at: null,
          updated_at: null,
          ...patch
        }
      ];
    });
  }

  async function saveAth(symbol: string) {
    const level = athLevels.find((item) => item.internal_symbol === symbol);
    if (!level) {
      return;
    }

    setSavingAthSymbol(symbol);
    setMessage(null);
    try {
      const next = await patchAthLevel(symbol, {
        mode: level.mode,
        ath_price: level.mode === "manual" ? level.ath_price : null
      });
      setAthLevels((current) => current.map((item) => (item.internal_symbol === symbol ? next : item)));
      setMessage(`ATH ${symbol} guardado`);
      onChanged?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo guardar ATH");
      void refreshAthLevels();
    } finally {
      setSavingAthSymbol(null);
    }
  }

  async function ensureTorumConfig(symbol: string, configs: StrategyConfig[], showPullbacks: boolean): Promise<StrategyConfig> {
    const existing = configs.find((config) => config.strategy_key === torumV1Key && config.internal_symbol === symbol);
    if (existing) {
      return patchStrategyConfig(existing.id, {
        timeframe: "H2",
        params_json: torumParams(symbol, existing.params_json, existing.enabled, showPullbacks)
      });
    }

    const strategySettings = await getStrategySettings();
    return createStrategyConfig({
      strategy_key: torumV1Key,
      internal_symbol: symbol,
      timeframe: "H2",
      enabled: false,
      mode: strategySettings.default_mode,
      params_json: torumParams(symbol, undefined, false, showPullbacks)
    });
  }

  async function updatePullbackDebug(enabled: boolean) {
    setShowPullbackDebug(enabled);
    setMessage(null);
    try {
      const configs = await getStrategyConfigs();
      await Promise.all(torumSymbols.map((symbol) => ensureTorumConfig(symbol, configs, enabled)));
      setMessage(enabled ? "Pullbacks visibles" : "Pullbacks ocultos");
      onChanged?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo guardar pullbacks");
      void refreshPullbackDebug();
    }
  }

  async function activatePush() {
    const status = await activatePushNotifications();
    setPushStatus(status);
    if (status === "missing-vapid") {
      setMessage("Faltan VAPID keys en backend");
    } else if (status === "subscribed") {
      setMessage("Push activado en este dispositivo");
    } else {
      setMessage(`Estado push: ${status}`);
    }
  }

  async function testPush() {
    try {
      const response = await sendTestPushNotification();
      setMessage(`${response.message}. Enviadas: ${response.sent}, fallidas: ${response.failed}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo enviar la prueba push");
    }
  }

  async function refreshMt5Execution() {
    try {
      setMt5Execution(await getMT5OrderExecutionSettings());
    } catch {
      setMt5Execution(null);
    }
  }

  async function save() {
    if (!settings) {
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      const updated = await patchTradingSettings({
        trading_mode: settings.trading_mode,
        long_only: settings.long_only,
        default_take_profit_percent: settings.default_take_profit_percent,
        use_stop_loss: settings.use_stop_loss,
        lot_per_equity_enabled: settings.lot_per_equity_enabled,
        equity_per_0_01_lot: settings.equity_per_0_01_lot,
        minimum_lot: settings.minimum_lot,
        allow_manual_lot_adjustment: settings.allow_manual_lot_adjustment,
        live_trading_enabled: settings.live_trading_enabled,
        require_live_confirmation: settings.require_live_confirmation,
        show_bid_line: settings.show_bid_line,
        show_ask_line: settings.show_ask_line,
        mt5_order_execution_enabled: settings.mt5_order_execution_enabled,
        market_data_source: settings.market_data_source
      });
      setSettings(updated);
      void refreshMt5Execution();
      setMessage("Ajustes guardados");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudieron guardar los ajustes");
    } finally {
      setSaving(false);
    }
  }

  if (!settings) {
    return <section className="panel mobile-settings-page">Cargando ajustes...</section>;
  }

  return (
    <section className="panel mobile-settings-page">
      <div className="panel-title">
        <Settings2 size={18} />
        Ajustes de trading
      </div>
      <section className="settings-card">
        <div className="settings-card__title">
          <Gauge size={18} />
          Modo y lotajes
        </div>
        <div className="settings-form-grid">
          <label>
            Modo
            <select value={settings.trading_mode} onChange={(event) => update("trading_mode", event.target.value as TradingMode)}>
              <option value="PAPER">PAPER</option>
              <option value="DEMO">DEMO</option>
              <option value="LIVE">LIVE</option>
            </select>
          </label>
          <label>
            Capital por 0.01 lote
            <input min="1" step="100" type="number" value={settings.equity_per_0_01_lot} onChange={(event) => update("equity_per_0_01_lot", Number(event.target.value))} />
          </label>
          <label>
            Lote minimo
            <input min="0.01" step="0.01" type="number" value={settings.minimum_lot} onChange={(event) => update("minimum_lot", Number(event.target.value))} />
          </label>
          <label>
            Take profit %
            <input min="0.01" step="0.01" type="number" value={settings.default_take_profit_percent} onChange={(event) => update("default_take_profit_percent", Number(event.target.value))} />
          </label>
        </div>
        <div className="settings-toggle-grid">
          <label className="toggle-line">
            <input checked={settings.long_only} type="checkbox" onChange={(event) => update("long_only", event.target.checked)} />
            Solo compras
          </label>
          <label className="toggle-line">
            <input checked={settings.lot_per_equity_enabled} type="checkbox" onChange={(event) => update("lot_per_equity_enabled", event.target.checked)} />
            Lotaje por equity
          </label>
          <label className="toggle-line">
            <input checked={settings.allow_manual_lot_adjustment} type="checkbox" onChange={(event) => update("allow_manual_lot_adjustment", event.target.checked)} />
            Permitir + / -
          </label>
          <label className="toggle-line">
            <input checked={settings.use_stop_loss} type="checkbox" onChange={(event) => update("use_stop_loss", event.target.checked)} />
            Usar stop loss
          </label>
        </div>
      </section>

      <section className="settings-card">
        <div className="settings-card__title">
          <Clock3 size={18} />
          Horarios
        </div>
        <div className="settings-form-grid">
          <label>
            Rango horario
            <select value={chartTimeMode} onChange={(event) => updateChartTimeMode(event.target.value as ChartTimeMode)}>
              <option value="auto">Automatico</option>
              <option value="manual">Manual</option>
            </select>
          </label>
          <label>
            Hora broker
            <select disabled={chartTimeMode === "auto"} value={chartBrokerUtcOffset} onChange={(event) => updateChartUtcOffset(chartManualBrokerUtcOffsetStorageKey, Number(event.target.value))}>
              {utcOffsetOptions.map((offset) => (
                <option key={offset} value={offset}>{formatUtcOffset(offset)}</option>
              ))}
            </select>
          </label>
          <label>
            Mi hora
            <select disabled={chartTimeMode === "auto"} value={chartLocalUtcOffset} onChange={(event) => updateChartUtcOffset(chartManualLocalUtcOffsetStorageKey, Number(event.target.value))}>
              {utcOffsetOptions.map((offset) => (
                <option key={offset} value={offset}>{formatUtcOffset(offset)}</option>
              ))}
            </select>
          </label>
        </div>
        <p className="notice-strip">Automatico mantiene la hora actual. Manual solo cambia la vista del grafico.</p>
      </section>

      <section className="settings-card">
        <div className="settings-card__title">
          <TrendingUp size={18} />
          ATH activos
        </div>
        <div className="ath-settings-grid">
          {torumSymbols.map((symbol) => {
            const level = athLevels.find((item) => item.internal_symbol === symbol) ?? {
              internal_symbol: symbol,
              ath_price: null,
              mode: "auto" as const,
              source: "candles",
              calculated_at: null,
              updated_at: null
            };
            return (
              <div className="ath-settings-row" key={symbol}>
                <strong>{symbol}</strong>
                <label>
                  Modo
                  <select value={level.mode} onChange={(event) => updateAth(symbol, { mode: event.target.value as AthLevel["mode"] })}>
                    <option value="auto">Automatico</option>
                    <option value="manual">Manual</option>
                  </select>
                </label>
                <label>
                  ATH
                  <input
                    disabled={level.mode === "auto"}
                    min="1"
                    step="0.01"
                    type="number"
                    value={level.ath_price ?? ""}
                    onChange={(event) => updateAth(symbol, { ath_price: event.target.value === "" ? null : Number(event.target.value) })}
                  />
                </label>
                <button className="toolbar-action" disabled={savingAthSymbol === symbol} type="button" onClick={() => void saveAth(symbol)}>
                  Guardar
                </button>
              </div>
            );
          })}
        </div>
        <p className="notice-strip">Manual manda sobre velas MT5. Automatico recalcula con velas importadas.</p>
      </section>

      <section className="settings-card">
        <div className="settings-card__title">
          <Eye size={18} />
          Visual
        </div>
        <div className="settings-toggle-grid">
          <label className="toggle-line">
            <input checked={settings.show_bid_line} type="checkbox" onChange={(event) => update("show_bid_line", event.target.checked)} />
            Mostrar linea BID
          </label>
          <label className="toggle-line">
            <input checked={settings.show_ask_line} type="checkbox" onChange={(event) => update("show_ask_line", event.target.checked)} />
            Mostrar linea ASK
          </label>
          <label className="toggle-line">
            <input checked={spyModeEnabled} type="checkbox" onChange={(event) => updateSpyMode(event.target.checked)} />
            <ScanEye size={16} />
            Modo espia
          </label>
          <label className="toggle-line">
            <input checked={showFutureNewsZones} type="checkbox" onChange={(event) => updateFutureNewsVisual(showFutureNewsZonesStorageKey, event.target.checked)} />
            Zonas futuras
          </label>
          <label className="toggle-line">
            <input checked={autoExtendToFutureNews} type="checkbox" onChange={(event) => updateFutureNewsVisual(autoExtendToFutureNewsStorageKey, event.target.checked)} />
            Extender tiempo futuro
          </label>
          <label className="toggle-line">
            <input checked={showPullbackDebug} type="checkbox" onChange={(event) => void updatePullbackDebug(event.target.checked)} />
            Mostrar pullbacks M5
          </label>
        </div>
      </section>

      <div className="danger-strip">Por defecto Torum compra sin stop loss y con TP automatico. LIVE sigue bloqueado si no activas sus protecciones.</div>
      <section className="settings-card settings-mt5-box">
        <div className="settings-card__title">
          <LineChart size={18} />
          Ejecucion MT5
        </div>
        <div className="settings-form-grid">
          <label>
            Fuente de mercado
            <select value={settings.market_data_source} onChange={(event) => update("market_data_source", event.target.value as TradingSettings["market_data_source"])}>
              <option value="MT5">MT5</option>
              <option value="MOCK">MOCK</option>
            </select>
          </label>
          <label className="toggle-line settings-toggle-inline">
            <input checked={settings.mt5_order_execution_enabled} type="checkbox" onChange={(event) => update("mt5_order_execution_enabled", event.target.checked)} />
            Habilitar ejecucion MT5
          </label>
        </div>
        <p className="notice-strip">Enviar ordenes demo o reales a MetaTrader 5 segun cuenta y modo.</p>
        <dl className="metric-list">
          <div>
            <dt>Torum</dt>
            <dd>{settings.mt5_order_execution_enabled ? "enabled" : "disabled"}</dd>
          </div>
          <div>
            <dt>Bridge</dt>
            <dd>{mt5Execution?.bridge_connected ? (mt5Execution.bridge_enabled ? "enabled" : "disabled") : "desconectado"}</dd>
          </div>
          <div>
            <dt>Estado</dt>
            <dd>{mt5Execution?.bridge_message || "Sin estado del bridge"}</dd>
          </div>
        </dl>
      </section>
      <section className="settings-card">
        <div className="settings-card__title">
          <Bell size={18} />
          Notificaciones
        </div>
        <dl className="metric-list">
          <div>
            <dt>Permiso</dt>
            <dd>{currentPushPermission()}</dd>
          </div>
          <div>
            <dt>Estado</dt>
            <dd>{pushStatus}</dd>
          </div>
        </dl>
        <div className="modal-actions">
          <button className="toolbar-action" type="button" onClick={() => void activatePush()}>
            Activar push
          </button>
          <button className="toolbar-action" type="button" onClick={() => void testPush()}>
            Enviar prueba
          </button>
        </div>
      </section>
      {message ? <div className="notice-strip">{message}</div> : null}
      <button className="primary-button" disabled={saving} type="button" onClick={() => void save()}>
        <Save size={18} />
        Guardar ajustes
      </button>
    </section>
  );
}
