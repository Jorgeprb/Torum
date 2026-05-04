import type { CSSProperties } from "react";
import { numericStyleValue } from "../drawings/drawingUtils";
import type { ChartLineStyle } from "./chartTypes";

export function clampNumber(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function clampedNumericStyleValue(
  style: Record<string, unknown>,
  key: string,
  fallback: number,
  min: number,
  max: number,
): number {
  return clampNumber(numericStyleValue(style, key, fallback), min, max);
}

export function lineStyleValue(style: Record<string, unknown>, fallback: ChartLineStyle = "solid"): ChartLineStyle {
  return style.lineStyle === "dashed" ? "dashed" : fallback;
}

export function cssLineStyle(lineStyle: ChartLineStyle): CSSProperties["borderTopStyle"] {
  return lineStyle === "dashed" ? "dashed" : "solid";
}

export function hexToRgba(color: string, opacity: number): string {
  const normalized = color.trim();
  const match = /^#([0-9a-f]{6})$/i.exec(normalized);
  if (!match) return normalized;

  const value = match[1];
  const red = parseInt(value.slice(0, 2), 16);
  const green = parseInt(value.slice(2, 4), 16);
  const blue = parseInt(value.slice(4, 6), 16);
  return `rgba(${red}, ${green}, ${blue}, ${clampNumber(opacity, 0, 1)})`;
}

export function colorInputValue(color: string, fallback: string): string {
  return /^#[0-9a-f]{6}$/i.test(color) ? color : fallback;
}
