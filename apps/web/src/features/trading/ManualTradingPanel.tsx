import { FormEvent, useEffect, useState } from "react";
import { AlertTriangle, Check, Send, X } from "lucide-react";

import { StatusPill } from "../../components/ui/StatusPill";
import {
  type ManualOrderPayload,
  type ManualOrderResponse,
  type TradingMode,
  type TradingSettings,
  getTradingSettings,
  patchTradingSettings,
  submitManualOrder
} from "../../services/trading";

interface ManualTradingPanelProps {
  symbol: string;
  accountMode: "DEMO" | "REAL" | "UNKNOWN";
  mt5Connected: boolean;
  onOrderCompleted: (response: ManualOrderResponse) => void;
  tradable?: boolean;
  disabledReason?: string;
}

export function ManualTradingPanel({
  symbol,
  accountMode,
  mt5Connected,
  onOrderCompleted,
  tradable = true,
  disabledReason
}: ManualTradingPanelProps) {
  const [settings, setSettings] = useState<TradingSettings | null>(null);
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [volume, setVolume] = useState("0.01");
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");
  const [comment, setComment] = useState("Manual order from Torum");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingLiveOrder, setPendingLiveOrder] = useState<ManualOrderPayload | null>(null);
  const [liveChecked, setLiveChecked] = useState(false);
  const [liveText, setLiveText] = useState("");

  useEffect(() => {
    void getTradingSettings().then((response) => {
      setSettings(response);
      setVolume(String(response.default_volume));
    });
  }, []);

  async function updateMode(mode: TradingMode) {
    const next = await patchTradingSettings({ trading_mode: mode });
    setSettings(next);
  }

  async function updateLiveEnabled(enabled: boolean) {
    const next = await patchTradingSettings({ live_trading_enabled: enabled });
    setSettings(next);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settings) {
      return;
    }
    if (!tradable) {
      setError(disabledReason ?? `${symbol} no esta habilitado para trading`);
      return;
    }
    const payload = buildPayload(settings.trading_mode);
    if (settings.trading_mode === "DEMO" && !window.confirm("Enviar orden DEMO a MT5?")) {
      return;
    }
    if (settings.trading_mode === "LIVE") {
      setPendingLiveOrder(payload);
      return;
    }
    await sendOrder(payload);
  }

  async function confirmLiveOrder() {
    if (!pendingLiveOrder || !settings) {
      return;
    }
    await sendOrder({
      ...pendingLiveOrder,
      client_confirmation: {
        confirmed: liveChecked,
        mode_acknowledged: "LIVE",
        live_text: liveText
      }
    });
    setPendingLiveOrder(null);
    setLiveChecked(false);
    setLiveText("");
  }

  async function sendOrder(payload: ManualOrderPayload) {
    setSubmitting(true);
    setError(null);
    try {
      const response = await submitManualOrder(payload);
      onOrderCompleted(response);
      if (!response.ok) {
        setError(response.reasons.join("; ") || response.message);
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo enviar la orden");
    } finally {
      setSubmitting(false);
    }
  }

  function buildPayload(mode: TradingMode): ManualOrderPayload {
    return {
      internal_symbol: symbol,
      side,
      order_type: "MARKET",
      volume: Number(volume),
      sl: sl ? Number(sl) : null,
      tp: tp ? Number(tp) : null,
      comment,
      client_confirmation: {
        confirmed: mode !== "LIVE",
        mode_acknowledged: mode
      }
    };
  }

  return (
    <section className="panel trading-ticket">
      <div className="panel-title">
        <Send size={18} />
        Orden manual
      </div>

      <div className="mode-row">
        <select value={settings?.trading_mode ?? "PAPER"} onChange={(event) => void updateMode(event.target.value as TradingMode)}>
          <option value="PAPER">PAPER</option>
          <option value="DEMO">DEMO</option>
          <option value="LIVE">LIVE</option>
        </select>
        <StatusPill label={`Cuenta ${accountMode}`} tone={accountMode === "REAL" ? "danger" : accountMode === "DEMO" ? "success" : "warning"} />
      </div>

      {settings?.trading_mode === "LIVE" ? (
        <div className="danger-strip">LIVE requiere habilitacion explicita y confirmacion fuerte.</div>
      ) : null}

      {!tradable ? <div className="notice-strip">{disabledReason ?? `${symbol} es solo analisis. Trading deshabilitado.`}</div> : null}

      <label className="toggle-line">
        <input
          type="checkbox"
          checked={settings?.live_trading_enabled ?? false}
          onChange={(event) => void updateLiveEnabled(event.target.checked)}
        />
        LIVE habilitado
      </label>

      <form className="trade-form" onSubmit={handleSubmit}>
        <div className="segmented-control segmented-control--wide">
          <button className={side === "BUY" ? "segment segment--active" : "segment"} type="button" onClick={() => setSide("BUY")}>
            BUY
          </button>
          <button className={side === "SELL" ? "segment segment--danger" : "segment"} type="button" onClick={() => setSide("SELL")}>
            SELL
          </button>
        </div>
        <label>
          Volumen
          <input value={volume} onChange={(event) => setVolume(event.target.value)} inputMode="decimal" />
        </label>
        <label>
          SL
          <input value={sl} onChange={(event) => setSl(event.target.value)} inputMode="decimal" placeholder="Opcional" />
        </label>
        <label>
          TP
          <input value={tp} onChange={(event) => setTp(event.target.value)} inputMode="decimal" placeholder="Opcional" />
        </label>
        <label>
          Comentario
          <input value={comment} onChange={(event) => setComment(event.target.value)} />
        </label>
        <button className="primary-button" type="submit" disabled={submitting || !settings || !tradable}>
          <Send size={18} />
          {submitting ? "Enviando" : "Enviar orden"}
        </button>
      </form>

      <div className="notice-strip">
        {settings?.trading_mode === "PAPER"
          ? "PAPER no envia ordenes a MT5."
          : mt5Connected
            ? "Las ordenes pasan por backend y mt5_bridge."
            : "MT5 desconectado: DEMO/LIVE se bloquearan."}
      </div>

      {error ? <div className="form-error">{error}</div> : null}

      {pendingLiveOrder ? (
        <div className="modal-backdrop">
          <div className="confirm-modal">
            <div className="panel-title">
              <AlertTriangle size={18} />
              Confirmacion LIVE
            </div>
            <p>Estas a punto de enviar una orden REAL a MT5. Esta operacion puede generar perdidas reales.</p>
            <label className="toggle-line">
              <input checked={liveChecked} onChange={(event) => setLiveChecked(event.target.checked)} type="checkbox" />
              Entiendo el riesgo real
            </label>
            <label>
              Escribe CONFIRM LIVE
              <input value={liveText} onChange={(event) => setLiveText(event.target.value)} />
            </label>
            <div className="modal-actions">
              <button className="icon-text-button" type="button" onClick={() => setPendingLiveOrder(null)}>
                <X size={18} />
                Cancelar
              </button>
              <button className="primary-button" type="button" onClick={() => void confirmLiveOrder()}>
                <Check size={18} />
                Confirmar LIVE
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
