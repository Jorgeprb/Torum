import { Bell, Clock3, Eye, Gauge, LineChart, Save, Search, ShieldCheck, SlidersHorizontal, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  type AthLevel,
  type MT5OrderExecutionSettings,
  type TradingSettings,
  getAthLevels,
  getMT5OrderExecutionSettings,
  getTradingSettings,
  patchAthLevel,
  patchTradingSettings,
} from "../../services/trading";
import { activatePushNotifications, currentPushPermission, getPushStatus, sendTestPushNotification, type PushStatus } from "../alerts/pushNotifications";
import { readChartDensity, saveChartDensity, type ChartDensity } from "../chart/chartDensitySettings";
import { readTradeExecutionMarkerSettings, saveTradeExecutionMarkerSetting } from "../trading/tradeExecutionMarkerSettings";

interface TradingSettingsPageProps { onChanged?: () => void }
type Category = "GENERAL" | "MANUAL" | "RISK" | "CHART" | "MT5" | "NOTIFICATIONS" | "ADVANCED";
type DisplayMode = "SIMPLE" | "ADVANCED";

const symbols = ["XAUEUR", "XAUUSD"];
const categories: Array<{ id: Category; label: string }> = [
  { id: "GENERAL", label: "General" },
  { id: "MANUAL", label: "Operativa manual" },
  { id: "RISK", label: "Riesgo y ATH" },
  { id: "CHART", label: "Gráfico" },
  { id: "MT5", label: "Datos y MT5" },
  { id: "NOTIFICATIONS", label: "Notificaciones" },
  { id: "ADVANCED", label: "Avanzado" },
];
const spyModeStorageKey = "torum.spyMode";
const showFutureNewsZonesStorageKey = "torum.showFutureNewsZones";
const autoExtendToFutureNewsStorageKey = "torum.autoExtendToFutureNews";
const chartTimeModeStorageKey = "torum.chartTimeMode";
const chartManualBrokerUtcOffsetStorageKey = "torum.chartManualBrokerUtcOffset";
const chartManualLocalUtcOffsetStorageKey = "torum.chartManualLocalUtcOffset";

function readBoolean(key: string, fallback: boolean) {
  try { const value = localStorage.getItem(key); return value === null ? fallback : value === "1"; } catch { return fallback; }
}
function writeBoolean(key: string, value: boolean, event?: string) {
  localStorage.setItem(key, value ? "1" : "0");
  if (event) window.dispatchEvent(new Event(event));
}
function same(a: unknown, b: unknown) { return JSON.stringify(a) === JSON.stringify(b); }

export function TradingSettingsPage({ onChanged }: TradingSettingsPageProps = {}) {
  const [settings, setSettings] = useState<TradingSettings | null>(null);
  const [savedSettings, setSavedSettings] = useState<TradingSettings | null>(null);
  const [category, setCategory] = useState<Category>("GENERAL");
  const [displayMode, setDisplayMode] = useState<DisplayMode>("SIMPLE");
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [mt5, setMt5] = useState<MT5OrderExecutionSettings | null>(null);
  const [pushStatus, setPushStatus] = useState<PushStatus>("permission-required");
  const [athLevels, setAthLevels] = useState<AthLevel[]>([]);
  const [savingAth, setSavingAth] = useState<string | null>(null);
  const [spyMode, setSpyMode] = useState(() => readBoolean(spyModeStorageKey, false));
  const [futureNews, setFutureNews] = useState(() => readBoolean(showFutureNewsZonesStorageKey, true));
  const [extendFutureNews, setExtendFutureNews] = useState(() => readBoolean(autoExtendToFutureNewsStorageKey, true));
  const [density, setDensity] = useState<ChartDensity>(() => readChartDensity().density);
  const [markers, setMarkers] = useState(readTradeExecutionMarkerSettings);
  const [timeMode, setTimeMode] = useState(() => localStorage.getItem(chartTimeModeStorageKey) ?? "auto");
  const [brokerOffset, setBrokerOffset] = useState(() => Number(localStorage.getItem(chartManualBrokerUtcOffsetStorageKey) ?? 3));
  const [localOffset, setLocalOffset] = useState(() => Number(localStorage.getItem(chartManualLocalUtcOffsetStorageKey) ?? 2));

  const dirty = Boolean(settings && savedSettings && !same(settings, savedSettings));
  const q = query.trim().toLowerCase();
  const show = (text: string) => !q || text.toLowerCase().includes(q);

  useEffect(() => {
    void Promise.all([getTradingSettings(), getMT5OrderExecutionSettings(), getAthLevels(), getPushStatus()])
      .then(([next, mt5Status, ath, push]) => {
        setSettings(next); setSavedSettings(structuredClone(next)); setMt5(mt5Status); setAthLevels(ath); setPushStatus(push);
      })
      .catch((error: unknown) => setMessage(error instanceof Error ? error.message : "No se pudieron cargar los ajustes"));
  }, []);

  function update<K extends keyof TradingSettings>(key: K, value: TradingSettings[K]) {
    setSettings((current) => current ? { ...current, [key]: value } : current);
  }

  async function save() {
    if (!settings) return;
    setSaving(true);
    try {
      const next = await patchTradingSettings(settings);
      setSettings(next); setSavedSettings(structuredClone(next)); setMessage("Ajustes aplicados"); onChanged?.();
      setMt5(await getMT5OrderExecutionSettings());
    } catch (error) { setMessage(error instanceof Error ? error.message : "No se pudieron guardar"); }
    finally { setSaving(false); }
  }

  function updateAth(symbol: string, patch: Partial<AthLevel>) {
    setAthLevels((current) => current.map((item) => item.internal_symbol === symbol ? { ...item, ...patch } : item));
  }
  async function persistAth(symbol: string) {
    const level = athLevels.find((item) => item.internal_symbol === symbol); if (!level) return;
    setSavingAth(symbol);
    try { const next = await patchAthLevel(symbol, { mode: level.mode, ath_price: level.ath_price }); updateAth(symbol, next); setMessage(`ATH ${symbol} guardado`); }
    catch (error) { setMessage(error instanceof Error ? error.message : "No se pudo guardar ATH"); }
    finally { setSavingAth(null); }
  }

  const searchResults = useMemo(() => categories.filter((item) => show(item.label)), [query]);
  if (!settings) return <section className="settings-page"><div className="strategy-empty-state">Cargando ajustes…</div></section>;

  return (
    <section className="settings-page settings-page--v2">
      <header className="settings-hero">
        <div><p className="eyebrow">Configuración</p><h2>Ajustes de Torum</h2><p>Los cambios de cuenta se publican juntos. Las preferencias de dispositivo se guardan al instante.</p></div>
        <div className="segmented-control"><button className={displayMode === "SIMPLE" ? "segment segment--active" : "segment"} onClick={() => setDisplayMode("SIMPLE")} type="button">Sencillo</button><button className={displayMode === "ADVANCED" ? "segment segment--active" : "segment"} onClick={() => setDisplayMode("ADVANCED")} type="button">Avanzado</button></div>
      </header>
      <div className="settings-search"><Search size={17}/><input placeholder="Buscar: zoom, lotaje, TP, noticias…" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
      <nav className="settings-category-nav">{searchResults.map((item) => <button className={category === item.id ? "is-active" : ""} key={item.id} type="button" onClick={() => setCategory(item.id)}>{item.label}</button>)}</nav>

      {category === "GENERAL" ? <section className="settings-card"><div className="settings-card__title"><SlidersHorizontal size={18}/> General <span className="setting-scope-badge">CUENTA</span></div><div className="settings-form-grid">
        <label>Modo<select value={settings.trading_mode} onChange={(e) => update("trading_mode", e.target.value as TradingSettings["trading_mode"])}><option>PAPER</option><option>DEMO</option><option>LIVE</option></select><small>Modo operativo de la cuenta.</small></label>
        <label className="toggle-line"><input checked={settings.is_paused} type="checkbox" onChange={(e) => update("is_paused", e.target.checked)}/> Pausar nuevas órdenes</label>
        <label className="toggle-line"><input checked={settings.allow_market_orders} type="checkbox" onChange={(e) => update("allow_market_orders", e.target.checked)}/> Permitir órdenes MARKET</label>
      </div></section> : null}

      {category === "MANUAL" ? <section className="settings-card"><div className="settings-card__title"><Gauge size={18}/> Operativa manual <span className="setting-scope-badge">CUENTA</span></div><div className="settings-form-grid">
        <label>Lotaje por defecto<input min="0.01" step="0.01" type="number" value={settings.default_volume} onChange={(e) => update("default_volume", Number(e.target.value))}/></label>
        <label>Lotaje máximo<input min="0.01" step="0.01" type="number" value={settings.max_order_volume ?? ""} onChange={(e) => update("max_order_volume", e.target.value === "" ? null : Number(e.target.value))}/></label>
        <label>TP automático<input min="0.001" step="0.001" type="number" value={settings.default_take_profit_percent} onChange={(e) => update("default_take_profit_percent", Number(e.target.value))}/><small>Porcentaje desde el precio real ejecutado.</small></label>
        <label>Capital por 0,01 lotes<input min="1" step="1" type="number" value={settings.equity_per_0_01_lot} onChange={(e) => update("equity_per_0_01_lot", Number(e.target.value))}/></label>
        <label className="toggle-line"><input checked={settings.lot_per_equity_enabled} type="checkbox" onChange={(e) => update("lot_per_equity_enabled", e.target.checked)}/> Lotaje por capital</label>
        <label className="toggle-line"><input checked={settings.allow_manual_lot_adjustment} type="checkbox" onChange={(e) => update("allow_manual_lot_adjustment", e.target.checked)}/> Permitir ajuste +/-</label>
        <label className="toggle-line"><input checked={settings.long_only} type="checkbox" onChange={(e) => update("long_only", e.target.checked)}/> Solo compras</label>
        <label className="toggle-line"><input checked={settings.use_stop_loss} type="checkbox" onChange={(e) => update("use_stop_loss", e.target.checked)}/> Usar stop loss</label>
      </div></section> : null}

      {category === "RISK" ? <section className="settings-card"><div className="settings-card__title"><TrendingUp size={18}/> ATH por activo <span className="setting-scope-badge">CUENTA</span></div><div className="ath-settings-grid">{symbols.map((symbol) => {
        const level = athLevels.find((item) => item.internal_symbol === symbol) ?? { internal_symbol: symbol, ath_price: null, mode: "auto", source: "candles", calculated_at: null, updated_at: null } as AthLevel;
        return <div className="ath-settings-row" key={symbol}><strong>{symbol}</strong><label>Modo<select value={level.mode} onChange={(e) => updateAth(symbol, { mode: e.target.value as AthLevel["mode"] })}><option value="auto">Automático</option><option value="manual">Manual</option></select></label><label>ATH<input disabled={level.mode === "auto"} min="1" step="0.01" type="number" value={level.ath_price ?? ""} onChange={(e) => updateAth(symbol, { ath_price: e.target.value ? Number(e.target.value) : null })}/></label><button disabled={savingAth === symbol} onClick={() => void persistAth(symbol)} type="button">Guardar</button></div>;
      })}</div><p className="notice-strip">Las reglas de estrés y capacidad del bot se editan en Estrategia Torum.</p></section> : null}

      {category === "CHART" ? <><section className="settings-card"><div className="settings-card__title"><Eye size={18}/> Apariencia <span className="setting-scope-badge">DISPOSITIVO</span></div><div className="settings-form-grid">
        <label className="toggle-line"><input checked={settings.show_bid_line} type="checkbox" onChange={(e) => update("show_bid_line", e.target.checked)}/> Línea BID</label>
        <label className="toggle-line"><input checked={settings.show_ask_line} type="checkbox" onChange={(e) => update("show_ask_line", e.target.checked)}/> Línea ASK</label>
        <label>Densidad<select value={density} onChange={(e) => { const value = e.target.value as ChartDensity; setDensity(saveChartDensity(value).density); }}><option value="WIDE">Amplia</option><option value="NORMAL">Normal</option><option value="COMPACT">Compacta</option><option value="ULTRA">Muy compacta</option></select></label>
        <label className="toggle-line"><input checked={spyMode} type="checkbox" onChange={(e) => { setSpyMode(e.target.checked); writeBoolean(spyModeStorageKey, e.target.checked, "torum-spy-mode-changed"); }}/> Modo espía</label>
        <label className="toggle-line"><input checked={futureNews} type="checkbox" onChange={(e) => { setFutureNews(e.target.checked); writeBoolean(showFutureNewsZonesStorageKey, e.target.checked, "torum-future-news-visuals-changed"); }}/> Zonas futuras</label>
        <label className="toggle-line"><input checked={extendFutureNews} type="checkbox" onChange={(e) => { setExtendFutureNews(e.target.checked); writeBoolean(autoExtendToFutureNewsStorageKey, e.target.checked, "torum-future-news-visuals-changed"); }}/> Extender futuro</label>
        <label className="toggle-line"><input checked={markers.show_trade_execution_markers} type="checkbox" onChange={(e) => setMarkers(saveTradeExecutionMarkerSetting("show_trade_execution_markers", e.target.checked))}/> Marcadores de operaciones</label>
        <label className="toggle-line"><input checked={markers.trade_execution_markers_only_m5} type="checkbox" onChange={(e) => setMarkers(saveTradeExecutionMarkerSetting("trade_execution_markers_only_m5", e.target.checked))}/> Marcadores solo M5</label>
      </div></section><section className="settings-card"><div className="settings-card__title"><Clock3 size={18}/> Horario del gráfico <span className="setting-scope-badge">DISPOSITIVO</span></div><div className="settings-form-grid"><label>Modo<select value={timeMode} onChange={(e) => { setTimeMode(e.target.value); localStorage.setItem(chartTimeModeStorageKey, e.target.value); window.dispatchEvent(new Event("torum-chart-time-settings-changed")); }}><option value="auto">Automático</option><option value="manual">Manual</option></select></label><label>UTC broker<input disabled={timeMode === "auto"} min="-12" max="14" type="number" value={brokerOffset} onChange={(e) => { setBrokerOffset(Number(e.target.value)); localStorage.setItem(chartManualBrokerUtcOffsetStorageKey, e.target.value); }}/></label><label>Mi UTC<input disabled={timeMode === "auto"} min="-12" max="14" type="number" value={localOffset} onChange={(e) => { setLocalOffset(Number(e.target.value)); localStorage.setItem(chartManualLocalUtcOffsetStorageKey, e.target.value); }}/></label></div></section></> : null}

      {category === "MT5" ? <section className="settings-card"><div className="settings-card__title"><LineChart size={18}/> Datos y MetaTrader <span className="setting-scope-badge">SISTEMA</span></div><div className="settings-form-grid"><label>Fuente<select value={settings.market_data_source} onChange={(e) => update("market_data_source", e.target.value as TradingSettings["market_data_source"])}><option value="MT5">MT5</option><option value="MOCK">MOCK</option></select></label><label className="toggle-line"><input checked={settings.mt5_order_execution_enabled} type="checkbox" onChange={(e) => update("mt5_order_execution_enabled", e.target.checked)}/> Habilitar ejecución MT5</label></div><dl className="metric-list"><div><dt>Torum</dt><dd>{settings.mt5_order_execution_enabled ? "Habilitado" : "Deshabilitado"}</dd></div><div><dt>Bridge</dt><dd>{mt5?.bridge_connected ? (mt5.bridge_enabled ? "Habilitado" : "Deshabilitado") : "Desconectado"}</dd></div><div><dt>Mensaje</dt><dd>{mt5?.bridge_message ?? "Sin estado"}</dd></div></dl></section> : null}

      {category === "NOTIFICATIONS" ? <section className="settings-card"><div className="settings-card__title"><Bell size={18}/> Notificaciones <span className="setting-scope-badge">DISPOSITIVO</span></div><dl className="metric-list"><div><dt>Permiso</dt><dd>{currentPushPermission()}</dd></div><div><dt>Estado</dt><dd>{pushStatus}</dd></div></dl><div className="modal-actions"><button onClick={() => void activatePushNotifications().then(setPushStatus)} type="button">Activar push</button><button onClick={() => void sendTestPushNotification()} type="button">Enviar prueba</button></div></section> : null}

      {category === "ADVANCED" || (displayMode === "ADVANCED" && category === "GENERAL") ? <section className="settings-card"><div className="settings-card__title"><ShieldCheck size={18}/> Protección avanzada <span className="setting-scope-badge">SISTEMA</span></div><div className="settings-form-grid"><label>Magic number<input type="number" value={settings.default_magic_number} onChange={(e) => update("default_magic_number", Number(e.target.value))}/></label><label>Desviación MT5<input min="0" type="number" value={settings.default_deviation_points} onChange={(e) => update("default_deviation_points", Number(e.target.value))}/></label><label className="toggle-line"><input checked={settings.live_trading_enabled} type="checkbox" onChange={(e) => update("live_trading_enabled", e.target.checked)}/> Permitir LIVE</label><label className="toggle-line"><input checked={settings.require_live_confirmation} type="checkbox" onChange={(e) => update("require_live_confirmation", e.target.checked)}/> Confirmación reforzada LIVE</label><label className="toggle-line"><input checked={settings.allow_pending_orders} type="checkbox" onChange={(e) => update("allow_pending_orders", e.target.checked)}/> Órdenes pendientes</label></div><div className="danger-strip">LIVE solo debe activarse tras validar DEMO, TP, cierres, riesgo y sincronización.</div></section> : null}

      {message ? <div className="notice-strip">{message}</div> : null}
      {dirty ? <footer className="settings-save-bar"><div><SlidersHorizontal size={17}/><strong>Cambios de cuenta sin aplicar</strong><span>Las preferencias visuales ya se han guardado en este dispositivo.</span></div><button type="button" onClick={() => setSettings(structuredClone(savedSettings!))}>Descartar</button><button className="primary-button" disabled={saving} type="button" onClick={() => void save()}><Save size={17}/> {saving ? "Aplicando…" : "Aplicar cambios"}</button></footer> : null}
    </section>
  );
}
