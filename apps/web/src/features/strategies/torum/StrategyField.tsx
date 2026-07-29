import type { TorumFieldDescriptor } from "../../../services/strategies";

interface StrategyFieldProps {
  descriptor: TorumFieldDescriptor;
  value: unknown;
  onChange: (value: unknown) => void;
}

export function StrategyField({ descriptor, value, onChange }: StrategyFieldProps) {
  if (descriptor.type === "boolean") {
    return (
      <label className="strategy-flow-field strategy-flow-field--toggle">
        <span className="strategy-flow-field__copy">
          <strong>{descriptor.label}</strong>
          <small>{descriptor.description}</small>
        </span>
        <span className="strategy-flow-switch">
          <input
            aria-label={descriptor.label}
            checked={Boolean(value)}
            type="checkbox"
            onChange={(event) => onChange(event.target.checked)}
          />
          <span aria-hidden="true" />
        </span>
      </label>
    );
  }

  if (descriptor.type === "select") {
    return (
      <label className="strategy-flow-field">
        <span>{descriptor.label}</span>
        <select value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}>
          {descriptor.options.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        <small>{descriptor.description}</small>
      </label>
    );
  }

  if (descriptor.type === "multiselect") {
    const selected = new Set(Array.isArray(value) ? value.map(String) : []);
    return (
      <fieldset className="strategy-flow-field strategy-flow-field--chips">
        <legend>{descriptor.label}</legend>
        <div className="strategy-chip-row">
          {descriptor.options.map((option) => {
            const active = selected.has(option.value);
            return (
              <button
                className={active ? "strategy-chip strategy-chip--active" : "strategy-chip"}
                key={option.value}
                type="button"
                onClick={() => {
                  const next = new Set(selected);
                  if (active) next.delete(option.value); else next.add(option.value);
                  onChange(Array.from(next));
                }}
              >
                {option.label}
              </button>
            );
          })}
        </div>
        <small>{descriptor.description}</small>
      </fieldset>
    );
  }

  const numeric = descriptor.type === "number";
  return (
    <label className="strategy-flow-field">
      <span>{descriptor.label}{descriptor.unit ? ` · ${descriptor.unit}` : ""}</span>
      <input
        inputMode={numeric ? "decimal" : undefined}
        max={descriptor.maximum ?? undefined}
        min={descriptor.minimum ?? undefined}
        step={descriptor.step ?? undefined}
        type={descriptor.type === "time" ? "time" : numeric ? "number" : "text"}
        value={typeof value === "number" || typeof value === "string" ? value : ""}
        onChange={(event) => {
          if (!numeric) {
            onChange(event.target.value);
            return;
          }
          const raw = event.target.value;
          onChange(raw === "" ? "" : Number(raw));
        }}
      />
      <small>{descriptor.description}</small>
    </label>
  );
}
