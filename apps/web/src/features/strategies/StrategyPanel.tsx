import { ChevronDown, Power } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { Timeframe } from "../../services/market";
import {
  type StrategyConfig,
  type StrategyDefinition,
  type StrategySettings,
  createStrategyConfig,
  getStrategies,
  getStrategyConfigs,
  getStrategySettings,
  patchStrategyConfig,
  patchStrategySettings,
  registerDefaultStrategies,
} from "../../services/strategies";

const TORUM_V1_KEY = "torum_v1";
const torumSymbols = ["XAUEUR", "XAUUSD"];

interface StrategyPanelProps {
  symbols: string[];
  timeframes: Timeframe[];
  onChanged?: () => void;
}

function defaultTorumParams(symbol: string): Record<string, unknown> {
  return {
    enabled: true,
    use_news: true,
    timeframe: "H2",
    session_start: symbol === "XAUEUR" ? "09:00" : "15:30",
    session_end: symbol === "XAUEUR" ? "15:00" : "21:00",
    enable_operation_zones: true,
    entry_timeframe: "M5",
    pullback_threshold_pct: 0.20,
    pullback_lookback_bars: 12,
    show_pullback_debug: false,
    require_zone: true,
    one_position_per_symbol: true
  };
}

export function StrategyPanel({ symbols, timeframes, onChanged }: StrategyPanelProps) {
  void symbols;
  void timeframes;
  const [definitions, setDefinitions] = useState<StrategyDefinition[]>([]);
  const [configs, setConfigs] = useState<StrategyConfig[]>([]);
  const [settings, setSettings] = useState<StrategySettings | null>(null);
  const [torumExpanded, setTorumExpanded] = useState(false);

  const torumDefinition = useMemo(
    () => definitions.find((definition) => definition.key === TORUM_V1_KEY),
    [definitions]
  );
  const torumConfigs = useMemo(
    () => configs.filter((config) => config.strategy_key === TORUM_V1_KEY),
    [configs]
  );
  const torumEnabled = torumSymbols.every((symbol) => torumConfigs.some((config) => config.internal_symbol === symbol && config.enabled));
  const torumParams = useMemo(
    () => ({ ...defaultTorumParams("XAUUSD"), ...(torumConfigs[0]?.params_json ?? {}) }),
    [torumConfigs]
  );

  useEffect(() => {
    void refresh();
  }, []);

  async function refresh() {
    let [definitionResponse, configResponse, settingsResponse] = await Promise.all([
      getStrategies(),
      getStrategyConfigs(),
      getStrategySettings(),
    ]);
    if (!definitionResponse.some((definition) => definition.key === TORUM_V1_KEY)) {
      definitionResponse = await registerDefaultStrategies();
    }
    if (!settingsResponse.strategies_enabled || !settingsResponse.strategy_live_enabled) {
      settingsResponse = await patchStrategySettings({
        strategies_enabled: true,
        strategy_live_enabled: true
      });
    }
    setDefinitions(definitionResponse);
    setConfigs(configResponse);
    setSettings(settingsResponse);
  }

  async function handleSettingsPatch(patch: Partial<StrategySettings>) {
    const next = await patchStrategySettings(patch);
    setSettings(next);
    onChanged?.();
  }

  async function ensureTorumConfig(symbol: string, enabled: boolean): Promise<StrategyConfig> {
    const existing = torumConfigs.find((config) => config.internal_symbol === symbol);
    if (existing) {
      const updated = await patchStrategyConfig(existing.id, {
        enabled,
        params_json: { ...defaultTorumParams(symbol), ...existing.params_json, enabled }
      });
      setConfigs((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      return updated;
    }

    const created = await createStrategyConfig({
      strategy_key: TORUM_V1_KEY,
      internal_symbol: symbol,
      timeframe: "H2",
      enabled,
      mode: settings?.default_mode ?? "PAPER",
      params_json: defaultTorumParams(symbol)
    });
    setConfigs((current) => [...current, created]);
    return created;
  }

  async function handleToggleTorum(nextEnabled: boolean) {
    try {
      if (nextEnabled && (!settings?.strategies_enabled || !settings?.strategy_live_enabled)) {
        await handleSettingsPatch({
          strategies_enabled: true,
          strategy_live_enabled: true
        });
      }
      const updated = await Promise.all(torumSymbols.map((symbol) => ensureTorumConfig(symbol, nextEnabled)));
      setConfigs((current) => {
        const byId = new Map(current.map((config) => [config.id, config]));
        for (const config of updated) {
          byId.set(config.id, config);
        }
        return [...byId.values()].sort((left, right) => left.id - right.id);
      });
      onChanged?.();
    } catch {
      // La UI queda igual si falla el backend.
    }
  }

  async function updateTorumParams(patch: Record<string, unknown>) {
    try {
      const readyConfigs = await Promise.all(torumSymbols.map((symbol) => ensureTorumConfig(symbol, torumEnabled)));
      const updated = await Promise.all(
        readyConfigs.map((config) =>
          patchStrategyConfig(config.id, {
            params_json: {
              ...defaultTorumParams(config.internal_symbol),
              ...config.params_json,
              ...patch
            }
          })
        )
      );
      setConfigs((current) => {
        const byId = new Map(current.map((config) => [config.id, config]));
        for (const config of updated) {
          byId.set(config.id, config);
        }
        return [...byId.values()].sort((left, right) => left.id - right.id);
      });
      onChanged?.();
    } catch {
      // Silencio simple. La card refresca en siguiente carga.
    }
  }

  return (
    <section className="strategy-workbench">
      <section className="table-panel strategy-card strategy-card--torum">
        <div className="strategy-card__header strategy-card__header--power">
          <button
            aria-expanded={torumExpanded}
            className="strategy-card__summary-trigger"
            type="button"
            onClick={() => setTorumExpanded((current) => !current)}
          >
            <ChevronDown
              className={torumExpanded ? "strategy-card__chevron strategy-card__chevron--open" : "strategy-card__chevron"}
              size={18}
            />
            <strong>{torumDefinition?.name ?? "Estrategia Torum V1.0"}</strong>
          </button>
          <button
            aria-label={torumEnabled ? "Apagar estrategia Torum V1" : "Encender estrategia Torum V1"}
            aria-pressed={torumEnabled}
            className={torumEnabled ? "strategy-power-toggle strategy-power-toggle--on" : "strategy-power-toggle strategy-power-toggle--off"}
            type="button"
            onClick={() => void handleToggleTorum(!torumEnabled)}
          >
            <Power size={18} />
            <span>{torumEnabled ? "ON" : "OFF"}</span>
          </button>
        </div>
        {torumExpanded ? (
          <div className="strategy-card__body strategy-card__summary">
            <p>
              Bloquea o libera el BOT por activo segun horario, velas cerradas y noticias.
              El usuario manual siempre puede operar.
            </p>
            <div className="strategy-card__meta">
              <span>XAUEUR 09:00-15:00</span>
              <span>XAUUSD 15:30-21:00</span>
              <span>Noticias bloquean solo BOT</span>
            </div>
            <div className="strategy-torum-settings">
              <label className="toggle-line">
                <input
                  checked={torumParams.enable_operation_zones === true}
                  type="checkbox"
                  onChange={(event) => void updateTorumParams({ enable_operation_zones: event.target.checked })}
                />
                Zonas operativas
              </label>
              <label className="toggle-line">
                <input
                  checked={torumParams.show_pullback_debug === true}
                  type="checkbox"
                  onChange={(event) => void updateTorumParams({ show_pullback_debug: event.target.checked })}
                />
                Mostrar pullbacks M5 calculados
              </label>
              <label className="toggle-line">
                <input
                  checked={torumParams.require_zone !== false}
                  type="checkbox"
                  onChange={(event) => void updateTorumParams({ require_zone: event.target.checked })}
                />
                Requerir zona
              </label>
              <label className="toggle-line">
                <input
                  checked={torumParams.one_position_per_symbol !== false}
                  type="checkbox"
                  onChange={(event) => void updateTorumParams({ one_position_per_symbol: event.target.checked })}
                />
                Una posicion por activo
              </label>
              <label>
                Pullback %
                <input
                  min="0.01"
                  step="0.01"
                  type="number"
                  value={Number(torumParams.pullback_threshold_pct ?? 0.2)}
                  onChange={(event) => void updateTorumParams({ pullback_threshold_pct: Number(event.target.value) })}
                />
              </label>
              <label>
                Lookback M5
                <input
                  min="2"
                  step="1"
                  type="number"
                  value={Number(torumParams.pullback_lookback_bars ?? 12)}
                  onChange={(event) => void updateTorumParams({ pullback_lookback_bars: Number(event.target.value) })}
                />
              </label>
              <label>
                Entrada
                <input disabled value="M5" readOnly />
              </label>
            </div>
          </div>
        ) : null}
      </section>
    </section>
  );
}
