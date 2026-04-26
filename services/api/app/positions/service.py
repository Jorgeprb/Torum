from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.mt5.client import MT5BridgeClient, MT5BridgeClientError
from app.positions.models import Position
from app.positions.repository import get_position, list_positions
from app.ticks.models import Tick


class PositionService:
    def __init__(self, db: Session, mt5_client: MT5BridgeClient | None = None) -> None:
        self.db = db
        self.mt5_client = mt5_client or MT5BridgeClient()

    def list_with_prices(self, status: str | None = None, limit: int = 100) -> list[Position]:
        positions = list_positions(self.db, status=status, limit=limit)
        for position in positions:
            if position.status == "OPEN":
                self._update_position_price(position)
        self.db.commit()
        return positions

    def close_position(self, position_id: int) -> tuple[bool, str, Position | None]:
        position = get_position(self.db, position_id)
        if position is None:
            return False, "Position not found", None
        if position.status != "OPEN":
            return False, "Position is not open", position

        if position.mode == "PAPER":
            self._update_position_price(position)
            position.status = "CLOSED"
            position.closed_at = datetime.now(UTC)
            self.db.commit()
            return True, "Paper position closed", position

        if position.mt5_position_ticket is None:
            return False, "MT5 position ticket is missing", position

        try:
            response = self.mt5_client.close_position(
                position.mt5_position_ticket,
                {
                    "internal_symbol": position.internal_symbol,
                    "broker_symbol": position.broker_symbol,
                    "side": position.side,
                    "volume": position.volume,
                    "mode": position.mode,
                    "magic_number": position.magic_number,
                },
            )
        except MT5BridgeClientError as exc:
            return False, str(exc), position

        if not response.get("ok"):
            return False, str(response.get("comment") or "MT5 close rejected"), position

        position.status = "CLOSED"
        position.closed_at = datetime.now(UTC)
        position.current_price = _float_or_none(response.get("price")) or position.current_price
        position.raw_payload_json = response
        self.db.commit()
        return True, "MT5 position closed", position

    def close_all_paper(self) -> int:
        positions = self.list_with_prices(status="OPEN", limit=1000)
        count = 0
        for position in positions:
            if position.mode != "PAPER":
                continue
            position.status = "CLOSED"
            position.closed_at = datetime.now(UTC)
            count += 1
        self.db.commit()
        return count

    def _update_position_price(self, position: Position) -> None:
        latest_tick = self.db.scalar(
            select(Tick)
            .where(Tick.internal_symbol == position.internal_symbol)
            .order_by(Tick.time.desc(), Tick.id.desc())
            .limit(1)
        )
        if latest_tick is None:
            return
        current_price = latest_tick.bid if position.side == "BUY" else latest_tick.ask
        current_price = current_price or latest_tick.last or position.current_price
        if current_price is None:
            return
        position.current_price = current_price
        direction = 1 if position.side == "BUY" else -1
        position.profit = (current_price - position.open_price) * position.volume * direction


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
