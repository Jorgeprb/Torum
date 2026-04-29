import { Minus, Plus } from "lucide-react";

interface LotSizeControlProps {
  baseLot: number;
  effectiveLot: number;
  multiplier: number;
  lotInputValue: string;
  disabled?: boolean;
  onIncrement: () => void;
  onDecrement: () => void;
  onLotInputChange: (value: string) => void;
  onLotInputBlur: () => void;
}

export function LotSizeControl({
  baseLot,
  disabled = false,
  effectiveLot,
  lotInputValue,
  multiplier,
  onDecrement,
  onIncrement,
  onLotInputBlur,
  onLotInputChange
}: LotSizeControlProps) {
  return (
    <div className="lot-size-control" aria-label="Lotaje">
      <button aria-label="Reducir lotaje" disabled={disabled || multiplier <= 1} type="button" onClick={onDecrement}>
        <Minus size={18} />
      </button>
      <div className="lot-size-control__value">
        <input
          aria-label="Lotaje"
          disabled={disabled}
          inputMode="decimal"
          placeholder={effectiveLot.toFixed(2)}
          type="text"
          value={lotInputValue}
          onBlur={onLotInputBlur}
          onChange={(event) => onLotInputChange(event.target.value)}
          onFocus={(event) => event.currentTarget.select()}
        />
        <span>base {baseLot.toFixed(2)} x{multiplier}</span>
      </div>
      <button aria-label="Aumentar lotaje" disabled={disabled} type="button" onClick={onIncrement}>
        <Plus size={18} />
      </button>
    </div>
  );
}
