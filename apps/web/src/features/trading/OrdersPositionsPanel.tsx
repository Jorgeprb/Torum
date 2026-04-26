import { X } from "lucide-react";

import type { OrderRead, PositionRead } from "../../services/trading";

interface OrdersPositionsPanelProps {
  orders: OrderRead[];
  positions: PositionRead[];
  onClosePosition: (id: number) => void;
}

export function OrdersPositionsPanel({ orders, positions, onClosePosition }: OrdersPositionsPanelProps) {
  return (
    <section className="orders-area">
      <div className="table-panel">
        <div className="panel-title">Posiciones</div>
        <div className="compact-table">
          {positions.length === 0 ? <div className="table-empty">Sin posiciones</div> : null}
          {positions.map((position) => (
            <div className="table-row" key={position.id}>
              <span>{position.internal_symbol}</span>
              <span>{position.side}</span>
              <span>{position.volume}</span>
              <span>{position.open_price.toFixed(2)}</span>
              <span>{position.profit?.toFixed(2) ?? "--"}</span>
              <span>{position.mode}</span>
              <button className="icon-only" type="button" onClick={() => onClosePosition(position.id)} disabled={position.status !== "OPEN"}>
                <X size={15} />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="table-panel">
        <div className="panel-title">Ordenes</div>
        <div className="compact-table">
          {orders.length === 0 ? <div className="table-empty">Sin ordenes</div> : null}
          {orders.map((order) => (
            <div className="table-row table-row--orders" key={order.id}>
              <span>{new Date(order.created_at).toLocaleTimeString()}</span>
              <span>{order.internal_symbol}</span>
              <span>{order.side}</span>
              <span>{order.volume}</span>
              <span>{order.status}</span>
              <span>{order.mode}</span>
              <span>{order.rejection_reason ?? ""}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
