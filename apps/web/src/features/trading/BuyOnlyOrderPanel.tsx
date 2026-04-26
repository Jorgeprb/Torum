import { useEffect, useMemo, useState } from "react";
import { ArrowUp, Loader2, ShieldAlert } from "lucide-react";

import type { MT5Status } from "../../services/market";
import {
  type LotSizeResponse,
  type ManualOrderResponse,
  type TradingMode,
  type TradingSettings,
  getLotSize,
  getTradingSettings,
  submitManualOrder
} from "../../services/trading";
import { LotSizeControl } from "./LotSizeControl";

interface BuyOnlyOrderPanelProps {
  accountMode: "DEMO" | "REAL" | "UNKNOWN";
  disabledReason?: string;
  lastPrice?: number;
  mt5Connected: boolean;
  mt5Status: MT5Status | null;
  onOrderCompleted: (response: ManualOrderResponse) => void;
  symbol: string;
  tradable: boolean;
}

function calculateTp(price: number | undefined, percent: number): number | null {
  if (typeof price !== "number" || !Number.isFinite(price)) {
    return null;
  }
  return price * (1 + percent / 100);
}

export function BuyOnlyOrderPanel({
  accountMode,
  disabledReason,
  lastPrice,
  mt5Connected,
  mt5Status,
  onOrderCompleted,
  symbol,
  tradable
}: BuyOnlyOrderPanelProps) {
  const [settings, setSettings] = useState<TradingSettings | null>(null);
  const [lotSize, setLotSize] = useState<LotSizeResponse | null>(null);
  const [multiplier, setMultiplier] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [liveText, setLiveText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const tpPercent = settings?.default_take_profit_percent ?? 0.09;
  const previewTp = useMemo(() => calculateTp(lastPrice, tpPercent), [lastPrice, tpPercent]);
  const mode: TradingMode = settings?.trading_mode ?? "PAPER";
  const buyDisabled = !tradable || submitting || !settings || !lotSize || (mode !== "PAPER" && !mt5Connected);

  useEffect(() => {
    setMultiplier(1);
  }, [symbol]);

  useEffect(() => {
    let active = true;
    void getTradingSettings()
      .then((response) => {
        if (active) {
          setSettings(response);
        }
      })
      .catch((requestError) => {
        if (active) {
          setError(requestError instanceof Error ? requestError.message : "No se pudo cargar trading settings");
        }
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    void getLotSize(symbol, multiplier)
      .then((response) => {
        if (active) {
          setLotSize(response);
        }
      })
      .catch((requestError) => {
        if (active) {
          setError(requestError instanceof Error ? requestError.message : "No se pudo calcular el lotaje");
        }
      });
    return () => {
      active = false;
    };
  }, [multiplier, symbol]);

  async function confirmBuy() {
    if (!settings || !lotSize) {
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const response = await submitManualOrder({
        internal_symbol: symbol,
        side: "BUY",
        order_type: "MARKET",
        volume: lotSize.effective_lot,
        sl: null,
        tp_percent: settings.default_take_profit_percent,
        comment: "Manual BUY from Torum mobile",
        client_confirmation: {
          confirmed: true,
          mode_acknowledged: settings.trading_mode,
          live_text: settings.trading_mode === "LIVE" ? liveText : null,
          no_stop_loss_acknowledged: true
        }
      });
      setModalOpen(false);
      setLiveText("");
      onOrderCompleted(response);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo enviar la compra");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="buy-panel" aria-label="Compra rapida">
      <div className="buy-panel__quote">
        <span>BUY</span>
        <strong>{typeof lastPrice === "number" ? lastPrice.toFixed(2) : "--"}</strong>
      </div>

      <LotSizeControl
        baseLot={lotSize?.base_lot ?? settings?.minimum_lot ?? 0.01}
        disabled={!settings?.allow_manual_lot_adjustment}
        effectiveLot={lotSize?.effective_lot ?? settings?.minimum_lot ?? 0.01}
        multiplier={multiplier}
        onDecrement={() => setMultiplier((current) => Math.max(1, current - 1))}
        onIncrement={() => setMultiplier((current) => current + 1)}
      />

      <button className="buy-panel__button" disabled={buyDisabled} type="button" onClick={() => setModalOpen(true)}>
        {submitting ? <Loader2 className="spin" size={18} /> : <ArrowUp size={18} />}
        BUY
      </button>

      <div className="buy-panel__meta">
        <span>{mode}</span>
        <span>TP {tpPercent.toFixed(2)}%</span>
        <span>{previewTp ? previewTp.toFixed(2) : "TP --"}</span>
      </div>

      {!tradable ? <div className="compact-warning">{disabledReason}</div> : null}
      {mode !== "PAPER" && !mt5Connected ? <div className="compact-warning">MT5 desconectado: DEMO/LIVE bloqueado</div> : null}
      {error ? <div className="compact-error">{error}</div> : null}

      {modalOpen ? (
        <div className="modal-backdrop" role="presentation">
          <div className="confirm-modal buy-confirm-modal" role="dialog" aria-modal="true" aria-label="Confirmar compra">
            <div className="modal-title-row">
              <ShieldAlert size={20} />
              <h2>Confirmar compra</h2>
            </div>
            <dl className="confirm-summary">
              <div>
                <dt>Simbolo</dt>
                <dd>{symbol}</dd>
              </div>
              <div>
                <dt>Cuenta</dt>
                <dd>{accountMode}</dd>
              </div>
              <div>
                <dt>Modo</dt>
                <dd>{mode}</dd>
              </div>
              <div>
                <dt>Lotaje</dt>
                <dd>{lotSize?.effective_lot.toFixed(2)}</dd>
              </div>
              <div>
                <dt>Precio aprox.</dt>
                <dd>{typeof lastPrice === "number" ? lastPrice.toFixed(2) : "--"}</dd>
              </div>
              <div>
                <dt>TP automatico</dt>
                <dd>{previewTp ? previewTp.toFixed(2) : "--"}</dd>
              </div>
            </dl>
            <p>Esta orden no tendra stop loss. El TP lo recalcula y valida el backend antes de ejecutar.</p>
            {mode === "LIVE" ? (
              <label>
                Escribe CONFIRM LIVE
                <input value={liveText} onChange={(event) => setLiveText(event.target.value)} />
              </label>
            ) : null}
            <div className="modal-actions">
              <button className="toolbar-action" type="button" onClick={() => setModalOpen(false)}>
                Cancelar
              </button>
              <button className="primary-button" disabled={submitting || (mode === "LIVE" && liveText.trim().toUpperCase() !== "CONFIRM LIVE")} type="button" onClick={() => void confirmBuy()}>
                Confirmar BUY
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <span className="sr-only">{mt5Status?.account?.server ?? "Sin servidor MT5"}</span>
    </section>
  );
}
