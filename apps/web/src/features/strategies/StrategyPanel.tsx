import { Play, RefreshCw, Save, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { Timeframe } from "../../services/market";
import type { TradingMode } from "../../services/trading";
import {
  type StrategyConfig,
  type StrategyDefinition,
  type StrategyRun,
  type StrategySignal,
  type StrategySettings,
  createStrategyConfig,
  getStrategies,
  getStrategyConfigs,
  getStrategyRuns,
  getStrategySettings,
  getStrategySignals,
  patchStrategyConfig,
  patchStrategySettings,
  registerDefaultStrategies,
  runStrategyConfig
} from "../../services/strategies";

interface StrategyPanelProps {
  symbols: string[];
  timeframes: Timeframe[];
}

export function StrategyPanel({ symbols, timeframes }: StrategyPanelProps) {
  const [definitions, setDefinitions] = useState<StrategyDefinition[]>([]);
  const [configs, setConfigs] = useState<StrategyConfig[]>([]);
  const [settings, setSettings] = useState<StrategySettings | null>(null);
  const [signals, setSignals] = useState<StrategySignal[]>([]);
  const [runs, setRuns] = useState<StrategyRun[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState("example_sma_dxy_filter");
  const [selectedSymbol, setSelectedSymbol] = useState("XAUUSD");
  const [selectedTimeframe, setSelectedTimeframe] = useState<Timeframe>("H1");
  const [mode, setMode] = useState<TradingMode>("PAPER");
  const [paramsText, setParamsText] = useState("{}");
  const [message, setMessage] = useState<string | null>(null);

  const activeDefinition = useMemo(
    () => definitions.find((definition) => definition.key === selectedStrategy),
    [definitions, selectedStrategy]
  );

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    if (activeDefinition) {
      setParamsText(JSON.stringify(activeDefinition.default_params_json, null, 2));
    }
  }, [activeDefinition]);

  async function refresh() {
    const [definitionResponse, configResponse, settingsResponse, signalResponse, runResponse] = await Promise.all([
      getStrategies(),
      getStrategyConfigs(),
      getStrategySettings(),
      getStrategySignals(),
      getStrategyRuns()
    ]);
    setDefinitions(definitionResponse);
    setConfigs(configResponse);
    setSettings(settingsResponse);
    setSignals(signalResponse);
    setRuns(runResponse);
    if (definitionResponse.length > 0 && !definitionResponse.some((definition) => definition.key === selectedStrategy)) {
      setSelectedStrategy(definitionResponse[0].key);
    }
  }

  async function handleRegisterDefaults() {
    await registerDefaultStrategies();
    await refresh();
  }

  async function handleSettingsPatch(patch: Partial<StrategySettings>) {
    const next = await patchStrategySettings(patch);
    setSettings(next);
  }

  async function handleCreateConfig() {
    try {
      const params = JSON.parse(paramsText) as Record<string, unknown>;
      const created = await createStrategyConfig({
        strategy_key: selectedStrategy,
        internal_symbol: selectedSymbol,
        timeframe: selectedTimeframe,
        enabled: false,
        mode,
        params_json: params
      });
      setConfigs((current) => [...current, created]);
      setMessage("Strategy config creada desactivada");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo crear la config");
    }
  }

  async function handleToggleConfig(config: StrategyConfig) {
    const updated = await patchStrategyConfig(config.id, { enabled: !config.enabled });
    setConfigs((current) => current.map((item) => (item.id === updated.id ? updated : item)));
  }

  async function handleRun(config: StrategyConfig) {
    try {
      const result = await runStrategyConfig(config.id);
      setMessage(result.ok ? result.message : result.reasons.join("; ") || result.message);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo ejecutar la estrategia");
    }
  }

  return (
    <section className="strategy-workbench">
      <section className="table-panel">
        <div className="panel-title">
          <ShieldAlert size={18} />
          Estrategias
        </div>
        <div className="notice-strip">Las estrategias estan desactivadas por defecto. Usa PAPER antes de DEMO/LIVE.</div>
        <div className="strategy-settings-grid">
          <label>
            <span>Engine</span>
            <input
              checked={settings?.strategies_enabled ?? false}
              type="checkbox"
              onChange={(event) => void handleSettingsPatch({ strategies_enabled: event.target.checked })}
            />
          </label>
          <label>
            <span>LIVE estrategias</span>
            <input
              checked={settings?.strategy_live_enabled ?? false}
              type="checkbox"
              onChange={(event) => void handleSettingsPatch({ strategy_live_enabled: event.target.checked })}
            />
          </label>
          <label>
            <span>Modo default</span>
            <select value={settings?.default_mode ?? "PAPER"} onChange={(event) => void handleSettingsPatch({ default_mode: event.target.value as TradingMode })}>
              <option value="PAPER">PAPER</option>
              <option value="DEMO">DEMO</option>
              <option value="LIVE" disabled={!settings?.strategy_live_enabled}>LIVE</option>
            </select>
          </label>
          <button className="secondary-button" type="button" onClick={handleRegisterDefaults}>
            <RefreshCw size={16} />
            Defaults
          </button>
        </div>
      </section>

      <section className="table-panel">
        <div className="panel-title">Nueva config</div>
        <div className="strategy-form">
          <select value={selectedStrategy} onChange={(event) => setSelectedStrategy(event.target.value)}>
            {definitions.map((definition) => (
              <option key={definition.key} value={definition.key}>{definition.name}</option>
            ))}
          </select>
          <select value={selectedSymbol} onChange={(event) => setSelectedSymbol(event.target.value)}>
            {symbols.map((symbol) => <option key={symbol} value={symbol}>{symbol}</option>)}
          </select>
          <select value={selectedTimeframe} onChange={(event) => setSelectedTimeframe(event.target.value as Timeframe)}>
            {timeframes.map((timeframe) => <option key={timeframe} value={timeframe}>{timeframe}</option>)}
          </select>
          <select value={mode} onChange={(event) => setMode(event.target.value as TradingMode)}>
            <option value="PAPER">PAPER</option>
            <option value="DEMO">DEMO</option>
            <option value="LIVE" disabled={!settings?.strategy_live_enabled}>LIVE</option>
          </select>
          <textarea value={paramsText} onChange={(event) => setParamsText(event.target.value)} />
          <button className="primary-button" type="button" onClick={handleCreateConfig}>
            <Save size={16} />
            Guardar config
          </button>
        </div>
      </section>

      <section className="table-panel">
        <div className="panel-title">Configs</div>
        <div className="compact-table">
          {configs.map((config) => (
            <div className="table-row table-row--strategies" key={config.id}>
              <span>{config.strategy_key}</span>
              <span>{config.internal_symbol}</span>
              <span>{config.timeframe}</span>
              <span>{config.mode}</span>
              <span>{config.enabled ? "ON" : "OFF"}</span>
              <button className="secondary-button" type="button" onClick={() => void handleToggleConfig(config)}>
                {config.enabled ? "Desactivar" : "Activar"}
              </button>
              <button className="secondary-button" disabled={!settings?.strategies_enabled || !config.enabled} type="button" onClick={() => void handleRun(config)}>
                <Play size={14} />
                Run
              </button>
            </div>
          ))}
          {configs.length === 0 ? <div className="table-empty">Sin configs de estrategias.</div> : null}
        </div>
      </section>

      <section className="table-panel">
        <div className="panel-title">Senales</div>
        <div className="compact-table">
          {signals.map((signal) => (
            <div className="table-row table-row--signals" key={signal.id}>
              <span>{new Date(signal.created_at).toLocaleTimeString()}</span>
              <span>{signal.strategy_key}</span>
              <span>{signal.internal_symbol}</span>
              <span>{signal.signal_type}</span>
              <span>{signal.side}</span>
              <span>{signal.status}</span>
              <span>{signal.reason}</span>
            </div>
          ))}
          {signals.length === 0 ? <div className="table-empty">Sin senales todavia.</div> : null}
        </div>
      </section>

      <section className="table-panel">
        <div className="panel-title">Runs</div>
        <div className="compact-table">
          {runs.map((run) => (
            <div className="table-row table-row--runs" key={run.id}>
              <span>{new Date(run.started_at).toLocaleTimeString()}</span>
              <span>{run.strategy_key}</span>
              <span>{run.status}</span>
              <span>{run.candles_used}</span>
              <span>{run.error_message ?? "--"}</span>
            </div>
          ))}
          {runs.length === 0 ? <div className="table-empty">Sin ejecuciones todavia.</div> : null}
        </div>
      </section>

      {message ? <section className="panel trade-message"><div>{message}</div></section> : null}
    </section>
  );
}
