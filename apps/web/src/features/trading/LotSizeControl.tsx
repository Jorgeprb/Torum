import { Minus, Plus } from "lucide-react";

interface LotSizeControlProps {
  baseLot: number;
  effectiveLot: number;
  multiplier: number;
  disabled?: boolean;
  onIncrement: () => void;
  onDecrement: () => void;
}

export function LotSizeControl({
  baseLot,
  disabled = false,
  effectiveLot,
  multiplier,
  onDecrement,
  onIncrement
}: LotSizeControlProps) {
  return (
    <div className="lot-size-control" aria-label="Lotaje">
      <button aria-label="Reducir lotaje" disabled={disabled || multiplier <= 1} type="button" onClick={onDecrement}>
        <Minus size={18} />
      </button>
      <div className="lot-size-control__value">
        <strong>{effectiveLot.toFixed(2)}</strong>
        <span>base {baseLot.toFixed(2)} x{multiplier}</span>
      </div>
      <button aria-label="Aumentar lotaje" disabled={disabled} type="button" onClick={onIncrement}>
        <Plus size={18} />
      </button>
    </div>
  );
}
