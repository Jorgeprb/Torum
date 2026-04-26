import { useEffect, useMemo, useState } from "react";
import { Activity, RefreshCw } from "lucide-react";

import {
  type IndicatorConfigRead,
  type IndicatorLineOutput,
  type IndicatorRead,
  getIndicatorConfigs,
  getIndicators,
  patchIndicatorConfig,
  registerDefaultIndicators
} from "../../services/indicators";

interface IndicatorsPanelProps {
  symbol: string;
  timeframe: string;
  indicatorLines: IndicatorLineOutput[];
  onChanged: () => void;
}

export function IndicatorsPanel({ symbol, timeframe, indicatorLines, onChanged }: IndicatorsPanelProps) {
  const [indicators, setIndicators] = useState<IndicatorRead[]>([]);
  const [configs, setConfigs] = useState<IndicatorConfigRead[]>([]);
  const [periodByConfig, setPeriodByConfig] = useState<Record<number, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const smaLine = useMemo(() => indicatorLines.find((line) => line.name.startsWith("SMA")), [indicatorLines]);

  useEffect(() => {
    void refresh();
  }, [symbol, timeframe]);

  async function refresh() {
    try {
      const [catalog, configList] = await Promise.all([getIndicators(), getIndicatorConfigs(symbol, timeframe)]);
      setIndicators(catalog);
      setConfigs(configList);
      setPeriodByConfig(
        Object.fromEntries(configList.map((config) => [config.id, String(config.params_json.period ?? 30)]))
      );
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudieron cargar indicadores");
    }
  }

  async function ensureDefaults() {
    setError(null);
    try {
      await registerDefaultIndicators();
      setMessage("Indicadores por defecto registrados");
      await refresh();
      onChanged();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudieron registrar indicadores");
    }
  }

  async function toggleConfig(config: IndicatorConfigRead) {
    const next = await patchIndicatorConfig(config.id, { enabled: !config.enabled });
    setConfigs((current) => current.map((item) => (item.id === next.id ? next : item)));
    onChanged();
  }

  async function savePeriod(config: IndicatorConfigRead) {
    const period = Number(periodByConfig[config.id] ?? 30);
    const next = await patchIndicatorConfig(config.id, { params_json: { ...config.params_json, period } });
    setConfigs((current) => current.map((item) => (item.id === next.id ? next : item)));
    setMessage(`Periodo actualizado a ${period}`);
    onChanged();
  }

  return (
    <section className="table-panel">
      <div className="panel-title">
        <Activity size={18} />
        Indicadores
      </div>
      <div className="indicator-summary">
        <span>Catalogo: {indicators.length}</span>
        <span>Activos: {configs.filter((config) => config.enabled).length}</span>
      </div>
      <button className="icon-text-button" type="button" onClick={() => void ensureDefaults()}>
        <RefreshCw size={18} />
        Registrar defaults
      </button>

      <div className="compact-table">
        {configs.length === 0 ? <div className="table-empty">Sin indicadores para {symbol} {timeframe}</div> : null}
        {configs.map((config) => (
          <div className="indicator-config-row" key={config.id}>
            <span>{indicatorName(config.indicator_id, indicators)}</span>
            <label className="toggle-line">
              <input checked={config.enabled} onChange={() => void toggleConfig(config)} type="checkbox" />
              Activo
            </label>
            <input
              inputMode="numeric"
              value={periodByConfig[config.id] ?? "30"}
              onChange={(event) => setPeriodByConfig((current) => ({ ...current, [config.id]: event.target.value }))}
            />
            <button className="icon-text-button" type="button" onClick={() => void savePeriod(config)}>
              Guardar
            </button>
          </div>
        ))}
      </div>

      {smaLine && smaLine.points.length === 0 ? (
        <div className="notice-strip">No hay suficientes velas para calcular {smaLine.name}. Se necesitan al menos 30 cierres.</div>
      ) : null}
      {message ? <div className="notice-strip">{message}</div> : null}
      {error ? <div className="form-error">{error}</div> : null}
    </section>
  );
}

function indicatorName(indicatorId: number, indicators: IndicatorRead[]): string {
  return indicators.find((indicator) => indicator.id === indicatorId)?.plugin_key ?? `Indicador ${indicatorId}`;
}
