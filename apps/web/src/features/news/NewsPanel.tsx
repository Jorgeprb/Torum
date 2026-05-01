import { FormEvent, useEffect, useMemo, useState } from "react";
import { FileJson, RefreshCw, ShieldAlert } from "lucide-react";

import {
  type NewsEvent,
  type NewsImportResponse,
  type NewsSettings,
  type NoTradeZone,
  getNewsEvents,
  getNewsSettings,
  importNewsCsv,
  importNewsJson,
  patchNewsSettings,
  regenerateNoTradeZones
} from "../../services/news";

interface NewsPanelProps {
  symbol: string;
  zones: NoTradeZone[];
  onChanged: () => void;
}

const defaultJson = JSON.stringify(
  {
    source: "manual",
    events: [
      {
        country: "United States",
        currency: "USD",
        impact: "HIGH",
        title: "Nonfarm Payrolls",
        event_time: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
        previous_value: "150K",
        forecast_value: "180K",
        actual_value: null
      }
    ]
  },
  null,
  2
);

const spainDateTimeFormatter = new Intl.DateTimeFormat("es-ES", {
  dateStyle: "short",
  timeStyle: "medium",
  timeZone: "Europe/Madrid"
});

function formatSpainDateTime(value: string): string {
  return spainDateTimeFormatter.format(new Date(value));
}

export function NewsPanel({ symbol, zones, onChanged }: NewsPanelProps) {
  const [settings, setSettings] = useState<NewsSettings | null>(null);
  const [events, setEvents] = useState<NewsEvent[]>([]);
  const [jsonText, setJsonText] = useState(defaultJson);
  const [csvText, setCsvText] = useState("country,currency,impact,title,event_time,previous_value,forecast_value,actual_value,source\n");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activeZones = useMemo(() => {
    const now = Date.now();
    return zones.filter((zone) => new Date(zone.start_time).getTime() <= now && new Date(zone.end_time).getTime() >= now);
  }, [zones]);

  useEffect(() => {
    void refresh();
  }, []);

  async function refresh() {
    try {
      const [settingsResponse, eventsResponse] = await Promise.all([getNewsSettings(), getNewsEvents()]);
      setSettings(settingsResponse);
      setEvents(eventsResponse);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudieron cargar noticias");
    }
  }

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settings) {
      return;
    }
    setMessage(null);
    setError(null);
    try {
      const next = await patchNewsSettings({
        draw_news_zones_enabled: settings.draw_news_zones_enabled,
        block_trading_during_news: settings.block_trading_during_news,
        minutes_before: settings.minutes_before,
        minutes_after: settings.minutes_after,
        currencies_filter: settings.currencies_filter,
        impact_filter: settings.impact_filter,
        countries_filter: settings.countries_filter,
        affected_symbols: settings.affected_symbols
      });
      setSettings(next);
      setMessage("Configuracion de noticias guardada y zonas regeneradas");
      onChanged();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo guardar configuracion");
    }
  }

  async function importJson() {
    setMessage(null);
    setError(null);
    try {
      const parsed = JSON.parse(jsonText) as { source?: string; events?: unknown[] };
      const response = await importNewsJson(parsed.source ?? "manual", parsed.events ?? []);
      handleImportResponse(response);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "JSON invalido");
    }
  }

  async function importCsv() {
    setMessage(null);
    setError(null);
    try {
      const response = await importNewsCsv("manual_csv", csvText);
      handleImportResponse(response);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "CSV invalido");
    }
  }

  async function regenerateZones() {
    setMessage(null);
    setError(null);
    try {
      const response = await regenerateNoTradeZones();
      setMessage(`Zonas regeneradas: ${response.regenerated}`);
      onChanged();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudieron regenerar zonas");
    }
  }

  function handleImportResponse(response: NewsImportResponse) {
    setMessage(`Eventos recibidos ${response.received}, guardados ${response.saved}, zonas ${response.zones_generated}`);
    if (response.errors.length > 0) {
      setError(response.errors.join("; "));
    }
    void refresh();
    onChanged();
  }

  return (
    <section className="news-workbench">
      <div className="table-panel">
        <div className="panel-title">
          <ShieldAlert size={18} />
          Noticias y zonas
        </div>
        <form className="news-settings-grid" onSubmit={saveSettings}>
          <label className="toggle-line">
            <input
              checked={settings?.draw_news_zones_enabled ?? true}
              onChange={(event) => settings && setSettings({ ...settings, draw_news_zones_enabled: event.target.checked })}
              type="checkbox"
            />
            Pintar zonas
          </label>
          <label className="toggle-line">
            <input
              checked={settings?.block_trading_during_news ?? false}
              onChange={(event) => settings && setSettings({ ...settings, block_trading_during_news: event.target.checked })}
              type="checkbox"
            />
            Bloquear operativa
          </label>
          <label>
            Min antes
            <input
              inputMode="numeric"
              value={settings?.minutes_before ?? 60}
              onChange={(event) => settings && setSettings({ ...settings, minutes_before: Number(event.target.value) })}
            />
          </label>
          <label>
            Min despues
            <input
              inputMode="numeric"
              value={settings?.minutes_after ?? 60}
              onChange={(event) => settings && setSettings({ ...settings, minutes_after: Number(event.target.value) })}
            />
          </label>
          <label>
            Divisas
            <input
              value={settings?.currencies_filter.join(",") ?? "USD"}
              onChange={(event) =>
                settings && setSettings({ ...settings, currencies_filter: event.target.value.split(",").map((value) => value.trim()) })
              }
            />
          </label>
          <label>
            Impacto
            <input
              value={settings?.impact_filter.join(",") ?? "HIGH"}
              onChange={(event) =>
                settings && setSettings({ ...settings, impact_filter: event.target.value.split(",").map((value) => value.trim()) })
              }
            />
          </label>
          <button className="primary-button" type="submit">
            Guardar
          </button>
          <button className="icon-text-button" type="button" onClick={() => void regenerateZones()}>
            <RefreshCw size={18} />
            Regenerar
          </button>
        </form>
        <div className={activeZones.some((zone) => zone.blocks_trading) ? "danger-strip" : "notice-strip"}>
          {activeZones.length > 0
            ? `${activeZones.length} zona(s) activas para ${symbol}`
            : `Sin zona activa para ${symbol}`}
        </div>
      </div>

      <div className="table-panel">
        <div className="panel-title">
          <FileJson size={18} />
          Importar JSON/CSV
        </div>
        <textarea className="news-import-area" value={jsonText} onChange={(event) => setJsonText(event.target.value)} />
        <button className="icon-text-button" type="button" onClick={() => void importJson()}>
          Importar JSON
        </button>
        <textarea className="news-import-area news-import-area--small" value={csvText} onChange={(event) => setCsvText(event.target.value)} />
        <button className="icon-text-button" type="button" onClick={() => void importCsv()}>
          Importar CSV
        </button>
        {message ? <div className="notice-strip">{message}</div> : null}
        {error ? <div className="form-error">{error}</div> : null}
      </div>

      <div className="table-panel">
        <div className="panel-title">Eventos</div>
        <div className="compact-table">
          {events.slice(0, 8).map((event) => (
            <div className="table-row table-row--news" key={event.id}>
              <span>{formatSpainDateTime(event.event_time)}</span>
              <span>{event.title}</span>
              <span>{event.currency}</span>
              <span>{event.impact}</span>
              <span>{event.forecast_value ?? "--"}</span>
            </div>
          ))}
          {events.length === 0 ? <div className="table-empty">Sin noticias importadas</div> : null}
        </div>
      </div>

      <div className="table-panel">
        <div className="panel-title">Zonas</div>
        <div className="compact-table">
          {zones.slice(0, 8).map((zone) => (
            <div className="table-row table-row--zones" key={zone.id}>
              <span>{zone.internal_symbol}</span>
              <span>{formatSpainDateTime(zone.start_time)}</span>
              <span>{formatSpainDateTime(zone.end_time)}</span>
              <span>{zone.blocks_trading ? "Bloquea" : "Visual"}</span>
              <span>{zone.reason}</span>
            </div>
          ))}
          {zones.length === 0 ? <div className="table-empty">Sin zonas para {symbol}</div> : null}
        </div>
      </div>
    </section>
  );
}
