import { useEffect, useMemo, useState } from "react";
import { RefreshCw, X } from "lucide-react";

import {
  type DollarStrengthSnapshot,
  getDollarStrength,
  recomputeDollarStrength
} from "../../services/marketContext";

interface DollarStrengthBadgeProps {
  compact?: boolean;
}

export function DollarStrengthBadge({ compact = false }: DollarStrengthBadgeProps) {
  const [snapshot, setSnapshot] = useState<DollarStrengthSnapshot | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void getDollarStrength()
      .then((response) => {
        if (active) setSnapshot(response);
      })
      .catch((requestError) => {
        if (active) setError(requestError instanceof Error ? requestError.message : "No se pudo cargar DXY");
      });
    return () => {
      active = false;
    };
  }, []);

  const tone = useMemo(() => {
    if (!snapshot || snapshot.state === "UNKNOWN" || snapshot.stale) return "unknown";
    return snapshot.trading_allowed ? "allowed" : "blocked";
  }, [snapshot]);

  async function handleRecompute() {
    setLoading(true);
    setError(null);
    try {
      const response = await recomputeDollarStrength();
      setSnapshot(response.snapshot);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo actualizar DXY");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={compact ? "dollar-strength dollar-strength--compact" : "dollar-strength"}>
      <button
        className={`dollar-strength__button dollar-strength__button--${tone}`}
        title="Fortaleza del dolar"
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          setOpen((current) => !current);
        }}
      >
        $
      </button>
      {open ? (
        <section className="dollar-strength__popover" onPointerDown={(event) => event.stopPropagation()}>
          <div className="dollar-strength__title">
            <strong>Filtro USD</strong>
            <button aria-label="Cerrar" type="button" onClick={() => setOpen(false)}>
              <X size={15} />
            </button>
          </div>
          <dl className="dollar-strength__metrics">
            <div>
              <dt>Estado</dt>
              <dd>{stateLabel(snapshot)}</dd>
            </div>
            <div>
              <dt>DXY</dt>
              <dd>{formatNumber(snapshot?.dxy_value)}</dd>
            </div>
            <div>
              <dt>SMA30</dt>
              <dd>{formatNumber(snapshot?.sma30)}</dd>
            </div>
            <div>
              <dt>Diferencia</dt>
              <dd>{formatNumber(snapshot?.difference)}</dd>
            </div>
            <div>
              <dt>Pendiente</dt>
              <dd>{snapshot?.slope_pct == null ? "--" : `${snapshot.slope_pct.toFixed(2)}% / ${snapshot.slope_days}d`}</dd>
            </div>
            <div>
              <dt>Motivo</dt>
              <dd>{snapshot?.reason ?? "usd_strength_unknown"}</dd>
            </div>
            <div>
              <dt>Actualizado</dt>
              <dd>{snapshot?.updated_at ? new Date(snapshot.updated_at).toLocaleString() : "--"}</dd>
            </div>
            <div>
              <dt>Usados</dt>
              <dd>{snapshot?.symbols_used?.length ? snapshot.symbols_used.join(", ") : "--"}</dd>
            </div>
            <div>
              <dt>Faltan</dt>
              <dd>{snapshot?.missing_symbols?.length ? snapshot.missing_symbols.join(", ") : "--"}</dd>
            </div>
          </dl>
          {error ? <p className="dollar-strength__error">{error}</p> : null}
          <button className="dollar-strength__refresh" disabled={loading} type="button" onClick={() => void handleRecompute()}>
            <RefreshCw size={14} />
            {loading ? "Actualizando" : "Actualizar"}
          </button>
        </section>
      ) : null}
    </div>
  );
}

function stateLabel(snapshot: DollarStrengthSnapshot | null): string {
  if (!snapshot) return "DESCONOCIDO";
  if (snapshot.state === "WEAK") return "DOLAR DEBIL";
  if (snapshot.state === "STRONG") return "DOLAR FUERTE";
  if (snapshot.state === "NEUTRAL") return "NEUTRO";
  return "DESCONOCIDO";
}

function formatNumber(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(3) : "--";
}
