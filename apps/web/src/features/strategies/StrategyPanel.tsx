import { Activity, ChevronDown, CircleHelp, Download, FlaskConical, Power, Save, Search, SlidersHorizontal, Undo2, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Timeframe } from "../../services/market";
import {
  type StrategyConfigVersion,
  type StrategySettings,
  type TorumFieldDescriptor,
  type TorumV1Configuration,
  getStrategyConfigVersions,
  getStrategySettings,
  getTorumV1Configuration,
  patchStrategySettings,
  patchTorumV1Configuration,
  restoreStrategyConfigVersion,
} from "../../services/strategies";
import { StrategyField } from "./torum/StrategyField";
import { StrategyVersions } from "./torum/StrategyVersions";

interface StrategyPanelProps {
  symbols: string[];
  timeframes: Timeframe[];
  onChanged?: () => void;
}

type Scope = "COMMON" | "XAUEUR" | "XAUUSD";
type EditorMode = "SIMPLE" | "ADVANCED";

const symbols = ["XAUEUR", "XAUUSD"] as const;

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function effectiveParams(configuration: TorumV1Configuration, scope: Scope): Record<string, unknown> {
  if (scope === "COMMON") return configuration.base_params;
  return { ...configuration.base_params, ...(configuration.asset_overrides[scope] ?? {}) };
}

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function StrategyPanel({ onChanged }: StrategyPanelProps) {
  const [configuration, setConfiguration] = useState<TorumV1Configuration | null>(null);
  const [savedConfiguration, setSavedConfiguration] = useState<TorumV1Configuration | null>(null);
  const [settings, setSettings] = useState<StrategySettings | null>(null);
  const [scope, setScope] = useState<Scope>("COMMON");
  const [editorMode, setEditorMode] = useState<EditorMode>("SIMPLE");
  const [query, setQuery] = useState("");
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set(["market", "pullback", "zone", "confirmation", "context", "risk"]));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [versions, setVersions] = useState<StrategyConfigVersion[]>([]);
  const [restoring, setRestoring] = useState<number | null>(null);
  const [changeNote, setChangeNote] = useState("");
  const importInputRef = useRef<HTMLInputElement | null>(null);

  const dirty = useMemo(
    () => Boolean(configuration && savedConfiguration && !same(configuration, savedConfiguration)),
    [configuration, savedConfiguration],
  );

  const visibleFields = useMemo(() => {
    if (!configuration) return [];
    const normalizedQuery = query.trim().toLowerCase();
    return configuration.schema.fields.filter((field) => {
      if (editorMode === "SIMPLE" && field.advanced) return false;
      if (!normalizedQuery) return true;
      return `${field.label} ${field.description} ${field.group}`.toLowerCase().includes(normalizedQuery);
    });
  }, [configuration, editorMode, query]);

  const groupedFields = useMemo(() => {
    if (!configuration) return [];
    return configuration.schema.groups
      .slice()
      .sort((a, b) => a.order - b.order)
      .map((group) => ({ group, fields: visibleFields.filter((field) => field.group === group.key) }))
      .filter((item) => item.fields.length > 0);
  }, [configuration, visibleFields]);

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (scope === "COMMON" || !configuration?.configs[scope]) {
      setVersions([]);
      return;
    }
    void getStrategyConfigVersions(configuration.configs[scope].id).then(setVersions).catch(() => setVersions([]));
  }, [configuration, scope]);

  async function load() {
    try {
      const [nextConfiguration, nextSettings] = await Promise.all([
        getTorumV1Configuration(),
        getStrategySettings(),
      ]);
      setConfiguration(clone(nextConfiguration));
      setSavedConfiguration(clone(nextConfiguration));
      setSettings(nextSettings);
      setMessage(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo cargar la estrategia");
    }
  }

  function updateAssetMeta(symbol: "XAUEUR" | "XAUUSD", patch: { enabled?: boolean; mode?: "PAPER" | "DEMO" | "LIVE" }) {
    setConfiguration((current) => {
      if (!current) return current;
      const next = clone(current);
      if (patch.enabled !== undefined) next.enabled_by_symbol[symbol] = patch.enabled;
      if (patch.mode !== undefined) next.mode_by_symbol[symbol] = patch.mode;
      return next;
    });
  }

  function updateField(field: TorumFieldDescriptor, value: unknown) {
    setConfiguration((current) => {
      if (!current) return current;
      const next = clone(current);
      if (scope === "COMMON") {
        next.base_params[field.key] = value;
      } else {
        next.asset_overrides[scope] = { ...(next.asset_overrides[scope] ?? {}), [field.key]: value };
      }
      return next;
    });
  }

  function restoreInheritance(field: TorumFieldDescriptor) {
    if (scope === "COMMON") return;
    setConfiguration((current) => {
      if (!current) return current;
      const next = clone(current);
      delete next.asset_overrides[scope]?.[field.key];
      return next;
    });
  }

  function toggleGroup(group: string) {
    setExpandedGroups((current) => {
      const next = new Set(current);
      if (next.has(group)) next.delete(group); else next.add(group);
      return next;
    });
  }

  async function toggleEngine() {
    if (!settings) return;
    try {
      const next = await patchStrategySettings({
        strategies_enabled: !settings.strategies_enabled,
        strategy_live_enabled: !settings.strategies_enabled ? settings.strategy_live_enabled : false,
      });
      setSettings(next);
      onChanged?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo cambiar el motor");
    }
  }

  async function save() {
    if (!configuration) return;
    setSaving(true);
    try {
      const next = await patchTorumV1Configuration({
        base_params: configuration.base_params,
        asset_overrides: configuration.asset_overrides,
        enabled_by_symbol: configuration.enabled_by_symbol,
        mode_by_symbol: configuration.mode_by_symbol,
        expected_revisions: Object.fromEntries(symbols.flatMap((symbol) => configuration.configs[symbol] ? [[symbol, configuration.configs[symbol].revision]] : [])),
        change_note: changeNote || "Actualización desde editor visual",
      });
      setConfiguration(clone(next));
      setSavedConfiguration(clone(next));
      setChangeNote("");
      setMessage("Configuración publicada");
      onChanged?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo publicar");
    } finally {
      setSaving(false);
    }
  }

  function applyPreset(name: "BASE" | "CONSERVATIVE" | "STRICT") {
    setConfiguration((current) => {
      if (!current) return current;
      const next = clone(current);
      const patch: Record<string, unknown> = name === "BASE"
        ? { pullback_entry_min_pct: 0.20, max_equivalent_positions: 3, risk_max_balance_pct: 50, confirmation_close_above_previous_high: false, usd_strength_strict: false }
        : name === "CONSERVATIVE"
          ? { pullback_entry_min_pct: 0.30, max_equivalent_positions: 2, risk_max_balance_pct: 35, confirmation_close_above_previous_high: true, usd_strength_strict: true }
          : { pullback_entry_min_pct: 0.40, max_equivalent_positions: 1, risk_max_balance_pct: 25, confirmation_close_above_previous_high: true, confirmation_min_body_pct: 0.03, usd_allow_when_neutral: false, usd_strength_strict: true };
      if (scope === "COMMON") next.base_params = { ...next.base_params, ...patch };
      else next.asset_overrides[scope] = { ...(next.asset_overrides[scope] ?? {}), ...patch };
      return next;
    });
    setMessage(`Preset ${name.toLowerCase()} aplicado como borrador`);
  }

  function exportConfiguration() {
    if (!configuration) return;
    const payload = {
      format: "torum-v1-configuration",
      version: 1,
      exported_at: new Date().toISOString(),
      base_params: configuration.base_params,
      asset_overrides: configuration.asset_overrides,
      enabled_by_symbol: configuration.enabled_by_symbol,
      mode_by_symbol: configuration.mode_by_symbol,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `torum-v1-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function importConfiguration(file: File) {
    try {
      const raw = JSON.parse(await file.text()) as Record<string, unknown>;
      if (raw.format !== "torum-v1-configuration" || typeof raw.base_params !== "object") {
        throw new Error("Archivo de configuración Torum V1 no válido");
      }
      setConfiguration((current) => current ? {
        ...clone(current),
        base_params: clone(raw.base_params as Record<string, unknown>),
        asset_overrides: clone((raw.asset_overrides ?? {}) as Record<string, Record<string, unknown>>),
        enabled_by_symbol: clone((raw.enabled_by_symbol ?? current.enabled_by_symbol) as Record<string, boolean>),
        mode_by_symbol: clone((raw.mode_by_symbol ?? current.mode_by_symbol) as TorumV1Configuration["mode_by_symbol"]),
      } : current);
      setMessage("Configuración importada como borrador; revisa y publica para aplicarla");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo importar");
    } finally {
      if (importInputRef.current) importInputRef.current.value = "";
    }
  }

  async function restoreVersion(revision: number) {
    if (!configuration || scope === "COMMON") return;
    const config = configuration.configs[scope];
    if (!config) return;
    setRestoring(revision);
    try {
      await restoreStrategyConfigVersion(config.id, revision);
      await load();
      setMessage(`Revisión ${revision} restaurada`);
      onChanged?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo restaurar");
    } finally {
      setRestoring(null);
    }
  }

  if (!configuration || !settings) return <section className="strategy-workbench"><div className="strategy-empty-state">Cargando estrategia…</div></section>;

  const params = effectiveParams(configuration, scope);
  return (
    <section className="strategy-workbench strategy-workbench--v2">
      <header className="strategy-workbench__hero">
        <div>
          <p className="eyebrow">Editor visual</p>
          <h2>Estrategia Torum V1</h2>
          <p>Configura y publica el flujo con control de versiones. El laboratorio histórico está en el menú «Simulador».</p>
        </div>
        <button
          className={settings.strategies_enabled ? "strategy-power-toggle strategy-power-toggle--on" : "strategy-power-toggle strategy-power-toggle--off"}
          type="button"
          onClick={() => void toggleEngine()}
        >
          <Power size={18} /> {settings.strategies_enabled ? "MOTOR ON" : "MOTOR OFF"}
        </button>
      </header>

      <nav className="strategy-scope-tabs" aria-label="Alcance de configuración">
        {(["COMMON", ...symbols] as Scope[]).map((item) => (
          <button className={scope === item ? "is-active" : ""} key={item} type="button" onClick={() => setScope(item)}>
            {item === "COMMON" ? "Configuración común" : item}
            {item !== "COMMON" && Object.keys(configuration.asset_overrides[item] ?? {}).length > 0 ? <small>{Object.keys(configuration.asset_overrides[item] ?? {}).length} personalizados</small> : null}
          </button>
        ))}
      </nav>

      {scope !== "COMMON" ? (
        <section className="strategy-asset-controls" aria-label={`Ejecución de ${scope}`}>
          <label className="strategy-asset-toggle">
            <input
              type="checkbox"
              checked={configuration.enabled_by_symbol[scope] ?? true}
              onChange={(event) => updateAssetMeta(scope, { enabled: event.target.checked })}
            />
            <span>{configuration.enabled_by_symbol[scope] ?? true ? "Activo habilitado" : "Activo deshabilitado"}</span>
          </label>
          <label>
            <span>Modo de ejecución</span>
            <select
              value={configuration.mode_by_symbol[scope] ?? "PAPER"}
              onChange={(event) => updateAssetMeta(scope, { mode: event.target.value as "PAPER" | "DEMO" | "LIVE" })}
            >
              <option value="PAPER">Paper</option>
              <option value="DEMO">MetaTrader Demo</option>
              <option value="LIVE">MetaTrader Real</option>
            </select>
          </label>
          <small>Estos controles afectan solo a {scope}; las condiciones inferiores pueden seguir heredando la configuración común.</small>
        </section>
      ) : null}

      <div className="strategy-editor-toolbar">
        <label className="strategy-search"><Search size={16} /><input placeholder="Buscar condición…" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <div className="segmented-control">
          <button className={editorMode === "SIMPLE" ? "segment segment--active" : "segment"} type="button" onClick={() => setEditorMode("SIMPLE")}>Sencillo</button>
          <button className={editorMode === "ADVANCED" ? "segment segment--active" : "segment"} type="button" onClick={() => setEditorMode("ADVANCED")}>Avanzado</button>
        </div>
        <select className="strategy-preset-select" defaultValue="" aria-label="Aplicar preset" onChange={(event) => { const value = event.target.value as "BASE" | "CONSERVATIVE" | "STRICT" | ""; if (value) applyPreset(value); event.target.value = ""; }}>
          <option value="">Aplicar preset…</option>
          <option value="BASE">Base</option>
          <option value="CONSERVATIVE">Conservador</option>
          <option value="STRICT">Estricto</option>
        </select>
        <button className="toolbar-action" type="button" onClick={() => { window.location.hash = "/strategy/simulator"; }}><FlaskConical size={17} /> Abrir simulador</button>
        <button className="toolbar-action" type="button" onClick={exportConfiguration}><Download size={16} /> Exportar</button>
        <button className="toolbar-action" type="button" onClick={() => importInputRef.current?.click()}><Upload size={16} /> Importar</button>
        <input ref={importInputRef} hidden type="file" accept="application/json,.json" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importConfiguration(file); }} />
      </div>

      <div className="strategy-workbench__columns">
        <div className="strategy-flow-editor">
          {groupedFields.map(({ group, fields }) => {
            const expanded = expandedGroups.has(group.key) || Boolean(query);
            return (
              <section className="strategy-flow-group" key={group.key}>
                <button className="strategy-flow-group__header" type="button" onClick={() => toggleGroup(group.key)}>
                  <span className="strategy-flow-group__number">{String(group.order / 10).padStart(2, "0")}</span>
                  <span><strong>{group.label}</strong><small>{group.description}</small></span>
                  <ChevronDown className={expanded ? "is-open" : ""} size={18} />
                </button>
                {expanded ? (
                  <div className="strategy-flow-group__body">
                    {fields.map((field) => {
                      const inherited = scope !== "COMMON" && !(field.key in (configuration.asset_overrides[scope] ?? {}));
                      return (
                        <div className="strategy-field-wrap" key={field.key}>
                          <StrategyField descriptor={field} value={params[field.key]} onChange={(value) => updateField(field, value)} />
                          {scope !== "COMMON" ? (
                            <button className="strategy-inherit-button" disabled={inherited} title="Volver al valor común" type="button" onClick={() => restoreInheritance(field)}>
                              <Undo2 size={14} /> {inherited ? "Heredado" : "Personalizado"}
                            </button>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </section>
            );
          })}
        </div>

        <aside className="strategy-inspector">
          <section className="settings-card strategy-simulator-shortcut">
            <div className="settings-card__title"><FlaskConical size={18} /> Laboratorio de estrategia</div>
            <p>El simulador completo incluye gráfico M5, entradas y salidas, métricas, equity, selección de regiones/soportes y traza de cada descarte.</p>
            <button className="primary-button" type="button" onClick={() => { window.location.hash = "/strategy/simulator"; }}><FlaskConical size={17} /> Ir al simulador</button>
          </section>
          <section className="settings-card">
            <div className="settings-card__title"><CircleHelp size={18} /> Publicación segura</div>
            <p>Los cambios no afectan al bot hasta pulsar «Publicar». El simulador del menú usa un borrador aislado y nunca envía órdenes.</p>
            <label className="strategy-flow-field">
              <span>Nota del cambio</span>
              <input maxLength={240} placeholder="Ej. Aumento PB mínimo" value={changeNote} onChange={(event) => setChangeNote(event.target.value)} />
            </label>
          </section>
          {scope !== "COMMON" ? <StrategyVersions versions={versions} restoring={restoring} onRestore={(revision) => void restoreVersion(revision)} /> : null}
        </aside>
      </div>

      {message ? <div className="notice-strip">{message}</div> : null}
      {dirty ? (
        <footer className="settings-save-bar">
          <div><SlidersHorizontal size={17} /><strong>Cambios sin publicar</strong><span>La estrategia activa todavía no ha cambiado.</span></div>
          <button type="button" onClick={() => setConfiguration(clone(savedConfiguration!))}>Descartar</button>
          <button className="primary-button" disabled={saving} type="button" onClick={() => void save()}><Save size={17} /> {saving ? "Publicando…" : "Publicar cambios"}</button>
        </footer>
      ) : null}
    </section>
  );
}
