import { FormEvent, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import {
  type NewsEvent,
  type NewsProviderStatus,
  type NewsSettings,
  type NoTradeZone,
  getNewsEvents,
  getNewsProviderStatus,
  getNewsSettings,
  getNoTradeZones,
  patchNewsSettings,
  syncNewsProvider
} from "../../services/news";

interface NewsProviderPageProps {
  onChanged: () => void;
}

const providerOptions: NewsSettings["provider"][] = ["FINNHUB", "MANUAL"];
const spainDateTimeFormatter = new Intl.DateTimeFormat("es-ES", {
  dateStyle: "short",
  timeStyle: "medium",
  timeZone: "Europe/Madrid"
});

function formatSpainDateTime(value: string | null | undefined): string {
  if (!value) {
    return "--";
  }

  return spainDateTimeFormatter.format(new Date(value));
}

export function NewsProviderPage({ onChanged }: NewsProviderPageProps) {
  const [settings, setSettings] = useState<NewsSettings | null>(null);
  const [status, setStatus] = useState<NewsProviderStatus | null>(null);
  const [events, setEvents] = useState<NewsEvent[]>([]);
  const [zones, setZones] = useState<NoTradeZone[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    void refresh();
  }, []);

  async function refresh() {
    try {
      const now = new Date();
      const to = new Date(now.getTime() + 14 * 24 * 60 * 60 * 1000);
      const [settingsResponse, statusResponse, eventsResponse, zonesResponse] = await Promise.all([
        getNewsSettings(),
        getNewsProviderStatus(),
        getNewsEvents(),
        getNoTradeZones("XAUUSD", now.toISOString(), to.toISOString())
      ]);
      setSettings(settingsResponse);
      setStatus(statusResponse);
      setEvents(eventsResponse);
      setZones(zonesResponse);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo cargar noticias");
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
        provider: settings.provider,
        provider_enabled: settings.provider_enabled,
        auto_sync_enabled: settings.auto_sync_enabled,
        sync_interval_minutes: settings.sync_interval_minutes,
        days_ahead: settings.days_ahead,
        block_trading_during_news: settings.block_trading_during_news,
        draw_news_zones_enabled: settings.draw_news_zones_enabled,
        minutes_before: settings.minutes_before,
        minutes_after: settings.minutes_after
      });
      setSettings(next);
      setMessage("Guardado");
      onChanged();
      void refresh();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo guardar");
    }
  }

  async function syncNow() {
    setSyncing(true);
    setMessage(null);
    setError(null);
    try {
      const response = await syncNewsProvider();
      setMessage(`Sync ${response.status}: ${response.saved} noticias, ${response.zones_generated} zonas`);
      if (response.errors.length > 0) {
        setError(response.errors.join("; "));
      }
      onChanged();
      void refresh();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo sincronizar");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <section className="news-provider-page">
      <div className="panel-title">Noticias</div>

      <section className="news-provider-status">
        <div>
          <span>Proveedor</span>
          <strong>{status?.provider ?? settings?.provider ?? "--"}</strong>
        </div>
        <div>
          <span>Estado</span>
          <strong>{status?.last_sync_status ?? "Pendiente"}</strong>
        </div>
        <div>
          <span>Ultima sync</span>
          <strong>{formatSpainDateTime(status?.last_sync_at)}</strong>
        </div>
        <div>
          <span>Proxima HIGH USD</span>
          <strong>{status?.next_event ? `${formatSpainDateTime(status.next_event.event_time)} ${status.next_event.title}` : "--"}</strong>
        </div>
      </section>

      <form className="news-provider-settings" onSubmit={saveSettings}>
        <label>
          Proveedor
          <select value={settings?.provider ?? "FINNHUB"} onChange={(event) => settings && setSettings({ ...settings, provider: event.target.value as NewsSettings["provider"] })}>
            {providerOptions.map((provider) => (
              <option key={provider} value={provider}>{provider}</option>
            ))}
          </select>
        </label>
        <label className="toggle-line">
          <input checked={settings?.provider_enabled ?? false} onChange={(event) => settings && setSettings({ ...settings, provider_enabled: event.target.checked })} type="checkbox" />
          Proveedor activo
        </label>
        <label className="toggle-line">
          <input checked={settings?.auto_sync_enabled ?? false} onChange={(event) => settings && setSettings({ ...settings, auto_sync_enabled: event.target.checked })} type="checkbox" />
          Auto sync
        </label>
        <label className="toggle-line">
          <input checked={settings?.block_trading_during_news ?? false} onChange={(event) => settings && setSettings({ ...settings, block_trading_during_news: event.target.checked })} type="checkbox" />
          Bloquear aperturas
        </label>
        <label className="toggle-line">
          <input checked={settings?.draw_news_zones_enabled ?? true} onChange={(event) => settings && setSettings({ ...settings, draw_news_zones_enabled: event.target.checked })} type="checkbox" />
          Dibujar zonas
        </label>
        <label>
          Intervalo min
          <input inputMode="numeric" value={settings?.sync_interval_minutes ?? 1440} onChange={(event) => settings && setSettings({ ...settings, sync_interval_minutes: Number(event.target.value) })} />
        </label>
        <label>
          Dias
          <input inputMode="numeric" value={settings?.days_ahead ?? 14} onChange={(event) => settings && setSettings({ ...settings, days_ahead: Number(event.target.value) })} />
        </label>
        <label>
          Min antes
          <input inputMode="numeric" value={settings?.minutes_before ?? 60} onChange={(event) => settings && setSettings({ ...settings, minutes_before: Number(event.target.value) })} />
        </label>
        <label>
          Min despues
          <input inputMode="numeric" value={settings?.minutes_after ?? 60} onChange={(event) => settings && setSettings({ ...settings, minutes_after: Number(event.target.value) })} />
        </label>
        <button className="primary-button" type="submit">Guardar</button>
        <button className="icon-text-button" disabled={syncing} type="button" onClick={() => void syncNow()}>
          <RefreshCw size={18} />
          Sincronizar ahora
        </button>
      </form>

      {message ? <div className="notice-strip">{message}</div> : null}
      {error || status?.last_sync_error ? <div className="form-error">{error ?? status?.last_sync_error}</div> : null}

      <section className="table-panel">
        <div className="panel-title">Noticias importadas</div>
        <div className="compact-table">
          {events.slice(0, 12).map((event) => (
            <div className="table-row table-row--news" key={event.id}>
              <span>{formatSpainDateTime(event.event_time)}</span>
              <span>{event.title}</span>
              <span>{event.currency}</span>
              <span>{event.impact}</span>
            </div>
          ))}
          {events.length === 0 ? <div className="table-empty">Sin noticias</div> : null}
        </div>
      </section>

      <section className="table-panel">
        <div className="panel-title">Zonas generadas</div>
        <div className="compact-table">
          {zones.slice(0, 12).map((zone) => (
            <div className="table-row table-row--zones" key={zone.id}>
              <span>{zone.internal_symbol}</span>
              <span>{formatSpainDateTime(zone.start_time)}</span>
              <span>{formatSpainDateTime(zone.end_time)}</span>
              <span>{zone.blocks_trading ? "Bloquea" : "Visual"}</span>
            </div>
          ))}
          {zones.length === 0 ? <div className="table-empty">Sin zonas</div> : null}
        </div>
      </section>
    </section>
  );
}
