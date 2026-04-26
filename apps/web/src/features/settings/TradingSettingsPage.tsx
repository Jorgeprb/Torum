import { useEffect, useState } from "react";
import { Save } from "lucide-react";

import { type TradingMode, type TradingSettings, getTradingSettings, patchTradingSettings } from "../../services/trading";

export function TradingSettingsPage() {
  const [settings, setSettings] = useState<TradingSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    void getTradingSettings().then(setSettings).catch((error: unknown) => {
      setMessage(error instanceof Error ? error.message : "No se pudieron cargar los ajustes");
    });
  }, []);

  function update<K extends keyof TradingSettings>(key: K, value: TradingSettings[K]) {
    setSettings((current) => (current ? { ...current, [key]: value } : current));
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
        require_live_confirmation: settings.require_live_confirmation
      });
      setSettings(updated);
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

      <div className="danger-strip">Por defecto Torum compra sin stop loss y con TP automatico. LIVE sigue bloqueado si no activas sus protecciones.</div>
      {message ? <div className="notice-strip">{message}</div> : null}
      <button className="primary-button" disabled={saving} type="button" onClick={() => void save()}>
        <Save size={18} />
        Guardar ajustes
      </button>
    </section>
  );
}
