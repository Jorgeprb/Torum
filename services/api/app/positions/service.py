from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.mt5.schemas import MT5AccountPayload
from app.mt5.client import MT5BridgeClient, MT5BridgeClientError
from app.positions.models import Position
from app.positions.repository import get_position, list_positions
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
from app.ticks.service import latest_tick_order_by


class PositionService:
    def __init__(self, db: Session, mt5_client: MT5BridgeClient | None = None) -> None:
        self.db = db
        self.mt5_client = mt5_client or MT5BridgeClient()

    def list_with_prices(self, status: str | None = None, limit: int = 100, symbol: str | None = None) -> list[Position]:
        positions = list_positions(self.db, status=status, limit=limit, symbol=symbol)
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
            position.close_price = position.current_price
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
        position.close_price = _float_or_none(response.get("price")) or position.current_price
        position.current_price = position.close_price or position.current_price
        position.closing_deal_ticket = _int_or_none(response.get("deal"))
        position.close_payload_json = response
        position.raw_payload_json = {**(position.raw_payload_json or {}), "close_response": response}
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

    def modify_take_profit(self, position_id: int, tp: float) -> tuple[bool, str, Position | None]:
        position = get_position(self.db, position_id)
        if position is None:
            return False, "Position not found", None
        if position.status != "OPEN":
            return False, "Position is not open", position
        if position.side != "BUY":
            return False, "Only BUY position TP modification is supported", position
        if tp <= position.open_price:
            return False, "TP must be above entry price for BUY positions", position

        if position.mode == "PAPER":
            position.tp = tp
            position.raw_payload_json = {**(position.raw_payload_json or {}), "tp_modified_at": datetime.now(UTC).isoformat()}
            self.db.commit()
            self.db.refresh(position)
            return True, "Paper TP updated", position

        if position.mt5_position_ticket is None:
            return False, "MT5 position ticket is missing", position

        try:
            response = self.mt5_client.modify_position_tp(
                position.mt5_position_ticket,
                {
                    "internal_symbol": position.internal_symbol,
                    "broker_symbol": position.broker_symbol,
                    "side": position.side,
                    "mode": position.mode,
                    "tp": tp,
                    "sl": 0,
                    "magic_number": position.magic_number,
                    "comment": "tp",
                },
            )
        except MT5BridgeClientError as exc:
            return False, str(exc), position

        if not response.get("ok"):
            return False, str(response.get("comment") or "MT5 TP modification rejected"), position

        position.tp = _float_or_none(response.get("price")) or tp
        position.raw_payload_json = response
        self.db.commit()
        self.db.refresh(position)
        return True, "MT5 TP updated", position

    def sync_mt5_positions(
        self,
        *,
        positions: list[dict[str, Any]],
        account: MT5AccountPayload | None,
        closed_deals: list[dict[str, Any]] | None = None,
    ) -> dict[str, int]:
        account_login = account.login if account else None
        account_server = account.server if account else None
        mode = "LIVE" if account and account.trade_mode == "REAL" else "DEMO" if account and account.trade_mode == "DEMO" else "DEMO"
        seen_tickets: set[int] = set()
        close_deals_by_position = _latest_close_deals_by_position(closed_deals or [])
        created = 0
        updated = 0

        for raw in positions:
            ticket = _int_or_none(raw.get("ticket") or raw.get("identifier"))
            if ticket is None:
                continue
            seen_tickets.add(ticket)
            broker_symbol = str(raw.get("symbol") or raw.get("broker_symbol") or "")
            if not broker_symbol:
                continue
            mapping = self.db.scalar(select(SymbolMapping).where(SymbolMapping.broker_symbol == broker_symbol).limit(1))
            internal_symbol = str(raw.get("internal_symbol") or (mapping.internal_symbol if mapping else broker_symbol)).upper()
            side = _side_from_mt5_position(raw)
            open_price = _float_or_none(raw.get("price_open") or raw.get("open_price")) or 0.0
            opened_at = _datetime_from_mt5_seconds(raw.get("time")) or datetime.now(UTC)
            position = self.db.scalar(select(Position).where(Position.mt5_position_ticket == ticket).limit(1))
            if position is None:
                position = Position(
                    user_id=None,
                    order_id=None,
                    internal_symbol=internal_symbol,
                    broker_symbol=broker_symbol,
                    mode=mode,
                    account_login=account_login,
                    account_server=account_server,
                    side=side,
                    volume=_float_or_none(raw.get("volume")) or 0.0,
                    open_price=open_price,
                    current_price=_float_or_none(raw.get("price_current")) or open_price,
                    sl=_float_or_none(raw.get("sl")),
                    tp=_float_or_none(raw.get("tp")),
                    profit=_float_or_none(raw.get("profit")),
                    status="OPEN",
                    mt5_position_ticket=ticket,
                    magic_number=_int_or_none(raw.get("magic")),
                    opened_at=opened_at,
                    raw_payload_json=raw,
                )
                self.db.add(position)
                created += 1
            else:
                position.internal_symbol = internal_symbol
                position.broker_symbol = broker_symbol
                position.mode = mode
                position.account_login = account_login or position.account_login
                position.account_server = account_server or position.account_server
                position.side = side
                position.volume = _float_or_none(raw.get("volume")) or position.volume
                position.current_price = _float_or_none(raw.get("price_current")) or position.current_price
                position.sl = _float_or_none(raw.get("sl"))
                position.tp = _float_or_none(raw.get("tp"))
                position.profit = _float_or_none(raw.get("profit"))
                position.status = "OPEN"
                position.raw_payload_json = raw
                updated += 1

        closed = self._close_missing_mt5_positions(
            seen_tickets,
            account_login=account_login,
            account_server=account_server,
            close_deals_by_position=close_deals_by_position,
        )
        self.db.commit()
        return {
            "created": created,
            "updated": updated,
            "closed": closed,
            "received": len(positions),
            "deals_received": len(closed_deals or []),
        }

    def _update_position_price(self, position: Position) -> None:
        latest_tick = self.db.scalar(
            select(Tick)
            .where(Tick.internal_symbol == position.internal_symbol)
            .order_by(*latest_tick_order_by())
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

    def _close_missing_mt5_positions(
        self,
        seen_tickets: set[int],
        *,
        account_login: int | None,
        account_server: str | None,
        close_deals_by_position: dict[int, dict[str, Any]],
    ) -> int:
        stmt = select(Position).where(
            Position.status == "OPEN",
            Position.mt5_position_ticket.is_not(None),
        )
        if account_login is not None:
            stmt = stmt.where(or_(Position.account_login == account_login, Position.account_login.is_(None)))
        if account_server:
            stmt = stmt.where(or_(Position.account_server == account_server, Position.account_server.is_(None)))
        count = 0
        for position in self.db.scalars(stmt):
            if position.mt5_position_ticket in seen_tickets:
                continue
            close_deal = close_deals_by_position.get(position.mt5_position_ticket)
            if close_deal is not None:
                _apply_close_deal(position, close_deal)
            else:
                self._update_position_price(position)
                position.close_price = position.current_price
                position.raw_payload_json = {**(position.raw_payload_json or {}), "closed_by_mt5_sync": True}
            position.status = "CLOSED"
            position.closed_at = position.closed_at or datetime.now(UTC)
            count += 1
        return count


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _datetime_from_mt5_seconds(value: object) -> datetime | None:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, UTC)


def _datetime_from_mt5_milliseconds(value: object) -> datetime | None:
    try:
        timestamp = float(value) / 1000
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, UTC)


def _latest_close_deals_by_position(deals: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    latest: dict[int, dict[str, Any]] = {}
    for deal in deals:
        position_id = _int_or_none(deal.get("position_id") or deal.get("position"))
        if position_id is None:
            continue
        current = latest.get(position_id)
        if current is None or _deal_sort_key(deal) >= _deal_sort_key(current):
            latest[position_id] = deal
    return latest


def _deal_sort_key(deal: dict[str, Any]) -> tuple[int, int]:
    time_msc = _int_or_none(deal.get("time_msc"))
    if time_msc is None:
        seconds = _int_or_none(deal.get("time")) or 0
        time_msc = seconds * 1000
    ticket = _int_or_none(deal.get("ticket")) or _int_or_none(deal.get("deal")) or 0
    return time_msc, ticket


def _apply_close_deal(position: Position, deal: dict[str, Any]) -> None:
    close_time = _datetime_from_mt5_milliseconds(deal.get("time_msc")) or _datetime_from_mt5_seconds(deal.get("time"))
    close_price = _float_or_none(deal.get("price"))
    position.closed_at = close_time or datetime.now(UTC)
    position.close_price = close_price or position.close_price or position.current_price
    position.current_price = position.close_price or position.current_price
    position.profit = _float_or_none(deal.get("profit")) if deal.get("profit") is not None else position.profit
    position.swap = _float_or_none(deal.get("swap"))
    position.commission = _float_or_none(deal.get("commission"))
    position.closing_deal_ticket = _int_or_none(deal.get("ticket") or deal.get("deal"))
    position.close_payload_json = deal.get("raw") if isinstance(deal.get("raw"), dict) else deal
    position.raw_payload_json = {
        **(position.raw_payload_json or {}),
        "closed_by_mt5_sync": True,
        "close_deal": deal,
    }


def _side_from_mt5_position(raw: dict[str, Any]) -> str:
    raw_side = str(raw.get("side") or "").upper()
    if raw_side in {"BUY", "SELL"}:
        return raw_side
    try:
        position_type = int(raw.get("type"))
    except (TypeError, ValueError):
        return "BUY"
    return "BUY" if position_type == 0 else "SELL"
