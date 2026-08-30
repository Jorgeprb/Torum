import { useEffect, useMemo, useState } from "react";

import type { StopOutLine } from "../../../services/risk";

export interface AccountStopOutLineVisualStyle {
  color: string;
  lineWidth: number;
  text: string;
}

interface AccountStopOutLineOverlayProps {
  line: StopOutLine | null | undefined;
  y: number | null;
  symbol: string;
}

const DEFAULT_STYLE: AccountStopOutLineVisualStyle = {
  color: "#ff4d67",
  lineWidth: 2,
  text: "STOP OUT"
};

function storageKey(symbol: string): string {
  return `torum.accountStopOutLineStyle.v1.${symbol.toUpperCase()}`;
}

function normalizeStyle(value: unknown): AccountStopOutLineVisualStyle {
  if (!value || typeof value !== "object") return DEFAULT_STYLE;
  const source = value as Record<string, unknown>;
  const width = Number(source.lineWidth);
  return {
    color: typeof source.color === "string" && /^#[0-9a-fA-F]{6}$/.test(source.color)
      ? source.color
      : DEFAULT_STYLE.color,
    lineWidth: Number.isFinite(width) ? Math.max(1, Math.min(6, Math.round(width))) : DEFAULT_STYLE.lineWidth,
    text: typeof source.text === "string" && source.text.trim() ? source.text.slice(0, 80) : DEFAULT_STYLE.text
  };
}

function loadStyle(symbol: string): AccountStopOutLineVisualStyle {
  try {
    const raw = window.localStorage.getItem(storageKey(symbol));
    return normalizeStyle(raw ? JSON.parse(raw) : null);
  } catch {
    return DEFAULT_STYLE;
  }
}

function saveStyle(symbol: string, style: AccountStopOutLineVisualStyle) {
  try {
    window.localStorage.setItem(storageKey(symbol), JSON.stringify(style));
  } catch {
    // Visual preference only.
  }
}

export function AccountStopOutLineOverlay({ line, y, symbol }: AccountStopOutLineOverlayProps) {
  const [style, setStyle] = useState<AccountStopOutLineVisualStyle>(() => loadStyle(symbol));
  const [editorOpen, setEditorOpen] = useState(false);

  useEffect(() => {
    setStyle(loadStyle(symbol));
    setEditorOpen(false);
  }, [symbol]);

  const correlationText = useMemo(() => {
    if (!line) return "";
    const correlation = line.correlation;
    const parts: string[] = [];
    if (typeof correlation.pearson === "number") {
      parts.push(`ρ H1 ${(correlation.pearson * 100).toFixed(1)}%`);
    }
    if (correlation.samples > 0) {
      parts.push(`${correlation.samples} muestras`);
    }
    if (line.correlated_other_symbol) {
      const beta = symbol.toUpperCase() === "XAUUSD"
        ? correlation.beta_xaueur_from_xauusd
        : correlation.beta_xauusd_from_xaueur;
      parts.push(`β ${beta.toFixed(3)} → ${line.correlated_other_symbol}`);
    }
    return parts.join(" · ");
  }, [line, symbol]);

  if (!line?.visible || line.price === null || y === null || !Number.isFinite(y)) {
    return null;
  }

  function patchStyle(patch: Partial<AccountStopOutLineVisualStyle>) {
    setStyle(current => {
      const next = normalizeStyle({ ...current, ...patch });
      saveStyle(symbol, next);
      return next;
    });
  }

  return (
    <>
      <div
        className="account-stopout-line"
        style={{
          top: y,
          color: style.color,
          ["--stopout-line-color" as string]: style.color,
          ["--stopout-line-width" as string]: `${style.lineWidth}px`
        }}
        onPointerDown={(event) => {
          event.stopPropagation();
        }}
      >
        <span className="account-stopout-line__segment" />
        <button
          className="account-stopout-line__label"
          type="button"
          title="Personalizar linea de Stop Out"
          onClick={(event) => {
            event.stopPropagation();
            setEditorOpen(current => !current);
          }}
        >
          {style.text}
        </button>
        <span className="account-stopout-line__segment" />
      </div>

      {editorOpen ? (
        <div
          className="account-stopout-style-editor"
          role="dialog"
          aria-label="Estilo de linea Stop Out"
          onPointerDown={(event) => event.stopPropagation()}
        >
          <div className="account-stopout-style-editor__header">
            <div>
              <strong>{symbol} · Stop Out estimado</strong>
              <small>{line.price.toFixed(2)} {line.account_currency ? `· cuenta ${line.account_currency}` : ""}</small>
            </div>
            <button type="button" onClick={() => setEditorOpen(false)} aria-label="Cerrar">×</button>
          </div>

          <label>
            <span>Texto central</span>
            <input
              maxLength={80}
              type="text"
              value={style.text}
              onChange={(event) => patchStyle({ text: event.target.value || "STOP OUT" })}
            />
          </label>

          <div className="account-stopout-style-editor__row">
            <label>
              <span>Color</span>
              <input
                type="color"
                value={style.color}
                onChange={(event) => patchStyle({ color: event.target.value })}
              />
            </label>
            <label className="account-stopout-style-editor__width">
              <span>Grosor</span>
              <input
                min="1"
                max="6"
                step="1"
                type="range"
                value={style.lineWidth}
                onChange={(event) => patchStyle({ lineWidth: Number(event.target.value) })}
              />
              <strong>{style.lineWidth}</strong>
            </label>
          </div>

          {correlationText ? <small className="account-stopout-style-editor__meta">{correlationText}</small> : null}
          <small className="account-stopout-style-editor__note">
            Línea fija: no se puede arrastrar. Marca el primer nivel estimado en el que MT5 alcanzaría Stop Out.
          </small>
        </div>
      ) : null}
    </>
  );
}
