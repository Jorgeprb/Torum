import { useEffect, useState } from "react";
import { Bell, Save } from "lucide-react";

import {
  type MT5OrderExecutionSettings,
  type TradingMode,
  type TradingSettings,
  getMT5OrderExecutionSettings,
  getTradingSettings,
  patchTradingSettings
} from "../../services/trading";
import {
  activatePushNotifications,
  currentPushPermission,
  getPushStatus,
  sendTestPushNotification,
  type PushStatus
} from "../alerts/pushNotifications";

export function TradingSettingsPage() {
  const [settings, setSettings] = useState<TradingSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [pushStatus, setPushStatus] = useState<PushStatus>("permission-required");
  const [mt5Execution, setMt5Execution] = useState<MT5OrderExecutionSettings | null>(null);

  useEffect(() => {
    void getTradingSettings().then(setSettings).catch((error: unknown) => {
      setMessage(error instanceof Error ? error.message : "No se pudieron cargar los ajustes");
    });
    void refreshMt5Execution();
    void getPushStatus().then(setPushStatus);
  }, []);

  function update<K extends keyof TradingSettings>(key: K, value: TradingSettings[K]) {
    setSettings((current) => (current ? { ...current, [key]: value } : current));
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
        <Save size={18} />
        Ajustes de trading
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
          <input
            min="1"
            step="100"
            type="number"
            value={settings.equity_per_0_01_lot}
            onChange={(event) => update("equity_per_0_01_lot", Number(event.target.value))}
          />
        </label>
        <label>
          Lote minimo
          <input
            min="0.01"
            step="0.01"
            type="number"
            value={settings.minimum_lot}
            onChange={(event) => update("minimum_lot", Number(event.target.value))}
          />
        </label>
        <label>
          Take profit %
          <input
            min="0.01"
            step="0.01"
            type="number"
            value={settings.default_take_profit_percent}
            onChange={(event) => update("default_take_profit_percent", Number(event.target.value))}
          />
        </label>
        <label>
          Fuente de mercado
          <select value={settings.market_data_source} onChange={(event) => update("market_data_source", event.target.value as TradingSettings["market_data_source"])}>
            <option value="MT5">MT5</option>
            <option value="MOCK">MOCK</option>
          </select>
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
        <label className="toggle-line">
          <input checked={settings.show_bid_line} type="checkbox" onChange={(event) => update("show_bid_line", event.target.checked)} />
          Mostrar linea BID
        </label>
        <label className="toggle-line">
          <input checked={settings.show_ask_line} type="checkbox" onChange={(event) => update("show_ask_line", event.target.checked)} />
          Mostrar linea ASK
        </label>
        <label className="toggle-line">
          <input
            checked={settings.mt5_order_execution_enabled}
            type="checkbox"
            onChange={(event) => update("mt5_order_execution_enabled", event.target.checked)}
          />
          Habilitar ejecucion MT5
        </label>
      </div>

      <div className="danger-strip">Por defecto Torum compra sin stop loss y con TP automatico. LIVE sigue bloqueado si no activas sus protecciones.</div>
      <section className="settings-push-box settings-mt5-box">
        <div className="panel-title">Ejecucion MT5</div>
        <p className="notice-strip">
          Activar ejecucion MT5 permite enviar ordenes demo o reales a MetaTrader 5 segun la cuenta conectada y el modo seleccionado. LIVE sigue requiriendo confirmacion fuerte y live_trading_enabled.
        </p>
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
      <section className="settings-push-box">
        <div className="panel-title">
          <Bell size={18} />
          Notificaciones push
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
