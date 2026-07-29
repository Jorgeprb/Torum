import { CalendarDays, CloudDownload, FileUp, Filter, Newspaper, Save, Settings2, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  type NewsEvent,
  type NewsImpactRule,
  type NewsProviderStatus,
  type NewsSettings,
  deleteNewsEvent,
  getNewsEvents,
  getNewsProviderStatus,
  getNewsSettings,
  importNewsCsv,
  importNewsJson,
  patchNewsSettings,
  syncNewsProvider,
} from "../../services/news";

type Tab = "SUMMARY" | "RULES" | "CALENDAR" | "PROVIDER" | "IMPORT";
const impacts = ["HIGH", "MEDIUM", "LOW"] as const;
const currencies = ["USD", "EUR", "GBP", "JPY", "CAD", "CHF", "SEK"];
const symbols = ["XAUUSD", "XAUEUR"];

function clone<T>(value: T): T { return JSON.parse(JSON.stringify(value)) as T; }
function same(a: unknown, b: unknown) { return JSON.stringify(a) === JSON.stringify(b); }

export function NewsProviderPage({ onChanged }: { onChanged?: () => void }) {
  const [tab, setTab] = useState<Tab>("SUMMARY");
  const [settings, setSettings] = useState<NewsSettings | null>(null);
  const [savedSettings, setSavedSettings] = useState<NewsSettings | null>(null);
  const [provider, setProvider] = useState<NewsProviderStatus | null>(null);
  const [events, setEvents] = useState<NewsEvent[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importText, setImportText] = useState("");
  const [importType, setImportType] = useState<"CSV" | "JSON">("CSV");
  const [impactFilter, setImpactFilter] = useState("");
  const [currencyFilter, setCurrencyFilter] = useState("");

  const dirty = Boolean(settings && savedSettings && !same(settings, savedSettings));
  const filteredEvents = useMemo(() => events.filter((event) => (!impactFilter || event.impact === impactFilter) && (!currencyFilter || event.currency === currencyFilter)), [events, impactFilter, currencyFilter]);
  const nextBlocking = useMemo(() => filteredEvents.find((event) => new Date(event.event_time).getTime() >= Date.now()), [filteredEvents]);

  useEffect(() => { void load(); }, []);

  async function load() {
    try {
      const [nextSettings, nextProvider, nextEvents] = await Promise.all([getNewsSettings(), getNewsProviderStatus(), getNewsEvents({ limit: 500 })]);
      setSettings(clone(nextSettings)); setSavedSettings(clone(nextSettings)); setProvider(nextProvider); setEvents(nextEvents);
    } catch (error) { setMessage(error instanceof Error ? error.message : "No se pudieron cargar las noticias"); }
  }

  function update<K extends keyof NewsSettings>(key: K, value: NewsSettings[K]) { setSettings((current) => current ? { ...current, [key]: value } : current); }
  function toggleList(key: "currencies_filter" | "affected_symbols", value: string) {
    if (!settings) return;
    const current = settings[key];
    update(key, (current.includes(value) ? current.filter((item) => item !== value) : [...current, value]) as NewsSettings[typeof key]);
  }
  function updateRule(impact: string, patch: Partial<NewsImpactRule>) {
    setSettings((current) => {
      if (!current) return current;
      const existing = current.impact_rules_json[impact];
      const nextRule: NewsImpactRule = {
        enabled: patch.enabled ?? existing?.enabled ?? true,
        minutes_before: patch.minutes_before ?? existing?.minutes_before ?? 0,
        minutes_after: patch.minutes_after ?? existing?.minutes_after ?? 0,
        action: patch.action ?? existing?.action ?? "DISPLAY",
      };
      return {
        ...current,
        impact_rules_json: { ...current.impact_rules_json, [impact]: nextRule },
        impact_filter: Array.from(new Set([...current.impact_filter, impact])),
      };
    });
  }

  async function save() {
    if (!settings) return;
    setSaving(true);
    try {
      const next = await patchNewsSettings({ ...settings, expected_revision: settings.revision });
      setSettings(clone(next)); setSavedSettings(clone(next)); setMessage("Reglas de noticias aplicadas"); onChanged?.();
      setProvider(await getNewsProviderStatus());
    } catch (error) { setMessage(error instanceof Error ? error.message : "No se pudieron guardar las reglas"); }
    finally { setSaving(false); }
  }

  async function sync() {
    setSyncing(true);
    try { const result = await syncNewsProvider(); setMessage(`Sincronización: ${result.saved} guardadas, ${result.zones_generated} zonas`); await load(); onChanged?.(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Falló la sincronización"); }
    finally { setSyncing(false); }
  }

  async function runImport() {
    if (!importText.trim()) return;
    setImporting(true);
    try {
      const result = importType === "CSV"
        ? await importNewsCsv("ui_csv", importText)
        : await importNewsJson("ui_json", JSON.parse(importText) as unknown[]);
      setMessage(`Importación: ${result.saved}/${result.received}. Zonas: ${result.zones_generated}`);
      setImportText(""); await load(); onChanged?.();
    } catch (error) { setMessage(error instanceof Error ? error.message : "No se pudo importar"); }
    finally { setImporting(false); }
  }

  async function removeEvent(event: NewsEvent) {
    const previous = events;
    setEvents((current) => current.filter((item) => item.id !== event.id));
    try { await deleteNewsEvent(event.id); onChanged?.(); }
    catch (error) { setEvents(previous); setMessage(error instanceof Error ? error.message : "No se pudo borrar"); }
  }

  function onFile(file: File) {
    const reader = new FileReader();
    reader.onload = () => { setImportText(String(reader.result ?? "")); setImportType(file.name.toLowerCase().endsWith(".json") ? "JSON" : "CSV"); };
    reader.readAsText(file);
  }

  if (!settings) return <section className="news-workspace"><div className="strategy-empty-state">Cargando noticias…</div></section>;

  return (
    <section className="news-workspace">
      <header className="settings-hero"><div><p className="eyebrow">Contexto de mercado</p><h2>Noticias</h2><p>Configura qué eventos se muestran, avisan o bloquean al bot.</p></div><button className="toolbar-action" disabled={syncing} type="button" onClick={() => void sync()}><CloudDownload size={17}/>{syncing ? "Sincronizando…" : "Sincronizar"}</button></header>
      <nav className="settings-category-nav">
        {(["SUMMARY", "RULES", "CALENDAR", "PROVIDER", "IMPORT"] as Tab[]).map((item) => <button className={tab === item ? "is-active" : ""} key={item} type="button" onClick={() => setTab(item)}>{({ SUMMARY: "Resumen", RULES: "Reglas de bloqueo", CALENDAR: "Calendario", PROVIDER: "Proveedor", IMPORT: "Importar" } as Record<Tab,string>)[item]}</button>)}
      </nav>

      {tab === "SUMMARY" ? <div className="news-summary-grid">
        <section className="settings-card"><div className="settings-card__title"><Newspaper size={18}/> Próximo evento</div>{provider?.next_event ? <><strong>{provider.next_event.title}</strong><p>{provider.next_event.currency} · {provider.next_event.impact} · {new Date(provider.next_event.event_time).toLocaleString()}</p></> : <p>Sin próximos eventos.</p>}</section>
        <section className="settings-card"><div className="settings-card__title"><CalendarDays size={18}/> Estado</div><dl className="metric-list"><div><dt>Eventos</dt><dd>{provider?.imported_events ?? events.length}</dd></div><div><dt>Zonas</dt><dd>{provider?.generated_zones ?? 0}</dd></div><div><dt>Última sync</dt><dd>{provider?.last_sync_at ? new Date(provider.last_sync_at).toLocaleString() : "Nunca"}</dd></div></dl></section>
        <section className="settings-card"><div className="settings-card__title"><Settings2 size={18}/> Regla activa</div><p>{nextBlocking ? `${nextBlocking.impact} ${nextBlocking.currency}: ${nextBlocking.title}` : "No hay bloqueo próximo en el rango cargado."}</p><button type="button" onClick={() => setTab("RULES")}>Editar reglas</button></section>
      </div> : null}

      {tab === "RULES" ? <section className="news-rule-builder">
        <section className="settings-card"><div className="settings-card__title"><Filter size={18}/> Alcance</div><p>Aplicar a divisas:</p><div className="strategy-chip-row">{currencies.map((item) => <button className={settings.currencies_filter.includes(item) ? "strategy-chip strategy-chip--active" : "strategy-chip"} key={item} onClick={() => toggleList("currencies_filter", item)} type="button">{item}</button>)}</div><p>Activos:</p><div className="strategy-chip-row">{symbols.map((item) => <button className={settings.affected_symbols.includes(item) ? "strategy-chip strategy-chip--active" : "strategy-chip"} key={item} onClick={() => toggleList("affected_symbols", item)} type="button">{item}</button>)}</div><label className="strategy-flow-field"><span>Compra manual durante noticia</span><select value={settings.manual_trade_policy} onChange={(e) => update("manual_trade_policy", e.target.value as NewsSettings["manual_trade_policy"])}><option value="ALLOW">Permitir</option><option value="WARN">Avisar</option><option value="REQUIRE_ACCEPTANCE">Exigir aceptación</option><option value="BLOCK">Bloquear</option></select></label></section>
        {impacts.map((impact) => { const rule = settings.impact_rules_json[impact] ?? { enabled: true, minutes_before: impact === "HIGH" ? 60 : 15, minutes_after: impact === "HIGH" ? 60 : 15, action: impact === "HIGH" ? "BLOCK_BOT" : "WARN" }; return <section className={`settings-card news-impact-rule news-impact-rule--${impact.toLowerCase()}`} key={impact}><div className="settings-card__title"><strong>{impact}</strong><label className="toggle-line"><input checked={rule.enabled} type="checkbox" onChange={(e) => updateRule(impact, { enabled: e.target.checked })}/>Activo</label></div><div className="settings-form-grid"><label>Minutos antes<input min="0" max="1440" type="number" value={rule.minutes_before} onChange={(e) => updateRule(impact, { minutes_before: Number(e.target.value) })}/></label><label>Minutos después<input min="0" max="1440" type="number" value={rule.minutes_after} onChange={(e) => updateRule(impact, { minutes_after: Number(e.target.value) })}/></label><label>Acción<select value={rule.action} onChange={(e) => updateRule(impact, { action: e.target.value as NewsImpactRule["action"] })}><option value="DISPLAY">Solo mostrar</option><option value="WARN">Avisar</option><option value="BLOCK_BOT">Bloquear bot</option><option value="BLOCK_ALL">Bloquear todo</option></select></label></div></section>; })}
      </section> : null}

      {tab === "CALENDAR" ? <section className="settings-card"><div className="settings-card__title"><CalendarDays size={18}/> Calendario</div><div className="news-filter-row"><select value={impactFilter} onChange={(e) => setImpactFilter(e.target.value)}><option value="">Todos los impactos</option>{impacts.map((item) => <option key={item}>{item}</option>)}</select><select value={currencyFilter} onChange={(e) => setCurrencyFilter(e.target.value)}><option value="">Todas las divisas</option>{currencies.map((item) => <option key={item}>{item}</option>)}</select></div><div className="news-calendar-list">{filteredEvents.map((event) => <article key={event.id}><time>{new Date(event.event_time).toLocaleString()}</time><span className={`news-impact-badge news-impact-badge--${event.impact.toLowerCase()}`}>{event.impact}</span><div><strong>{event.title}</strong><small>{event.currency} · {event.country} · {event.source}</small></div><button aria-label="Borrar evento" onClick={() => void removeEvent(event)} type="button"><Trash2 size={15}/></button></article>)}</div></section> : null}

      {tab === "PROVIDER" ? <section className="settings-card"><div className="settings-card__title"><CloudDownload size={18}/> Proveedor y sincronización</div><div className="settings-form-grid"><label>Proveedor<select value={settings.provider} onChange={(e) => update("provider", e.target.value as NewsSettings["provider"])}><option value="FINNHUB">Finnhub</option><option value="MANUAL">Manual</option></select></label><label className="toggle-line"><input checked={settings.provider_enabled} type="checkbox" onChange={(e) => update("provider_enabled", e.target.checked)}/>Proveedor activo</label><label className="toggle-line"><input checked={settings.auto_sync_enabled} type="checkbox" onChange={(e) => update("auto_sync_enabled", e.target.checked)}/>Sincronización automática</label><label>Intervalo (min)<input min="15" max="10080" type="number" value={settings.sync_interval_minutes} onChange={(e) => update("sync_interval_minutes", Number(e.target.value))}/></label><label>Días futuros<input min="1" max="90" type="number" value={settings.days_ahead} onChange={(e) => update("days_ahead", Number(e.target.value))}/></label></div><dl className="metric-list"><div><dt>Estado</dt><dd>{provider?.last_sync_status ?? "--"}</dd></div><div><dt>Error</dt><dd>{provider?.last_sync_error ?? "Ninguno"}</dd></div></dl></section> : null}

      {tab === "IMPORT" ? <section className="settings-card"><div className="settings-card__title"><FileUp size={18}/> Importación avanzada</div><label className="news-drop-zone" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); const file = e.dataTransfer.files[0]; if (file) onFile(file); }}><input accept=".csv,.json,text/csv,application/json" type="file" onChange={(e) => { const file = e.target.files?.[0]; if (file) onFile(file); }}/><FileUp size={26}/><strong>Arrastra CSV o JSON</strong><span>Se mostrará antes de importar.</span></label><div className="segmented-control"><button className={importType === "CSV" ? "segment segment--active" : "segment"} onClick={() => setImportType("CSV")} type="button">CSV</button><button className={importType === "JSON" ? "segment segment--active" : "segment"} onClick={() => setImportType("JSON")} type="button">JSON</button></div><textarea rows={12} placeholder={importType === "CSV" ? "event_time,title,currency,country,impact…" : '[{"event_time":"…"}]'} value={importText} onChange={(e) => setImportText(e.target.value)}/><button className="primary-button" disabled={importing || !importText.trim()} onClick={() => void runImport()} type="button">{importing ? "Importando…" : "Validar e importar"}</button></section> : null}

      {message ? <div className="notice-strip">{message}</div> : null}
      {dirty ? <footer className="settings-save-bar"><div><Settings2 size={17}/><strong>Cambios de noticias sin aplicar</strong><span>Las zonas se regenerarán al publicar.</span></div><button type="button" onClick={() => setSettings(clone(savedSettings!))}>Descartar</button><button className="primary-button" disabled={saving} onClick={() => void save()} type="button"><Save size={17}/>{saving ? "Aplicando…" : "Aplicar reglas"}</button></footer> : null}
    </section>
  );
}
