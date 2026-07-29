import type { TorumV1BacktestRequest } from "../../../services/strategies";

export type SimulatorSymbol = "XAUUSD" | "XAUEUR";
export type SimulatorPreset = "REALISTIC" | "CONSERVATIVE" | "TECHNICAL" | "CUSTOM";
export type SimulatorSetupStep = "MARKET" | "FILTERS" | "PARAMETERS" | "EXECUTION";
export type SimulatorRequestSettings = Omit<TorumV1BacktestRequest, "symbol" | "params" | "from_time" | "to_time">;

export interface SimulatorDrawingOption {
  id: string;
  label: string;
  kind: "ZONE" | "SUPPORT";
  level?: number;
}

export interface SimulatorValidationIssue {
  id: string;
  severity: "ERROR" | "WARNING" | "INFO";
  title: string;
  detail: string;
  step?: SimulatorSetupStep;
}
