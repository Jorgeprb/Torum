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

        safe_positions: list[Position] = []

        for position in positions:
            if position.status == "OPEN":
                if not self._is_really_open_position(position):
                    continue

                # IMPORTANTE:
                # En posiciones reales de MT5, el profit correcto es el que viene de MT5
                # por positions_get(), porque ya incluye contract size, divisa de cuenta,
                # conversión del broker, símbolo, etc.
                #
                # No recalculamos DEMO/LIVE aquí porque pisaríamos el profit real.
                if position.mode == "PAPER":
                    self._update_position_price(position)

            safe_positions.append(position)

        self.db.commit()
        return safe_positions

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
    def reconcile_missing_mt5_positions(self) -> dict[str, int]:
        """
        Cierra de forma defensiva posiciones DEMO/LIVE que Torum tiene como OPEN
        pero que no son seguras para pintar como vivas.

        Esta reconciliación NO borra nada.
        Solo marca como CLOSED las posiciones no PAPER sin mt5_position_ticket.
        Las posiciones con mt5_position_ticket deben cerrarse preferentemente por
        sync_mt5_positions() comparando contra positions_get().
        """
        stmt = select(Position).where(
            Position.status == "OPEN",
            Position.mode != "PAPER",
            Position.mt5_position_ticket.is_(None),
        )

        closed = 0

        for position in self.db.scalars(stmt):
            self._update_position_price(position)
            position.status = "CLOSED"
            position.closed_at = position.closed_at or datetime.now(UTC)
            position.close_price = position.close_price or position.current_price
            position.raw_payload_json = {
                **(position.raw_payload_json or {}),
                "closed_by_reconcile": True,
                "close_deal_missing": True,
                "close_reason": "Non-PAPER position without mt5_position_ticket cannot be considered live",
            }
            closed += 1

        self.db.commit()

        return {"closed": closed}
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

                # Si MT5 devuelve esta posición en positions_get(), entonces está abierta de verdad.
                # Limpiamos campos de cierre por seguridad, por si quedó una reconciliación antigua mal hecha.
                position.status = "OPEN"
                position.closed_at = None
                position.close_price = None
                position.closing_deal_ticket = None
                position.close_payload_json = None

                position.raw_payload_json = {
                    **(position.raw_payload_json or {}),
                    "mt5_open_position": raw,
                    "reopened_by_positions_get": True,
                }

                updated += 1

        updated += self._refresh_closed_mt5_position_deals(
            close_deals_by_position,
            account_login=account_login,
            account_server=account_server,
        )
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
        contract_size = self._contract_size(position)
        position.profit = _calculate_position_profit(
            open_price=position.open_price,
            current_price=current_price,
            volume=position.volume,
            side=position.side,
            contract_size=contract_size,
        )

    def _contract_size(self, position: Position) -> float:
        mapping = self.db.scalar(
            select(SymbolMapping)
            .where(SymbolMapping.internal_symbol == position.internal_symbol)
            .limit(1)
        )

        if mapping is None or mapping.contract_size <= 0:
            return 1.0

        return mapping.contract_size
    
    def _is_really_open_position(self, position: Position) -> bool:
        if position.status != "OPEN":
            return False

        if position.closed_at is not None:
            return False

        if position.close_price is not None:
            return False

        if position.mode != "PAPER" and position.mt5_position_ticket is None:
            return False

        return True

    def _refresh_closed_mt5_position_deals(
        self,
        close_deals_by_position: dict[int, dict[str, Any]],
        *,
        account_login: int | None,
        account_server: str | None,
    ) -> int:
        if not close_deals_by_position:
            return 0

        stmt = select(Position).where(
            Position.status == "CLOSED",
            Position.mt5_position_ticket.in_(list(close_deals_by_position.keys())),
        )
        if account_login is not None:
            stmt = stmt.where(or_(Position.account_login == account_login, Position.account_login.is_(None)))
        if account_server:
            stmt = stmt.where(or_(Position.account_server == account_server, Position.account_server.is_(None)))

        count = 0
        for position in self.db.scalars(stmt):
            if position.mt5_position_ticket is None:
                continue
            close_deal = close_deals_by_position.get(position.mt5_position_ticket)
            if close_deal is None:
                continue
            _apply_close_deal(position, close_deal)
            count += 1
        return count
    
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

                position.raw_payload_json = {
                    **(position.raw_payload_json or {}),
                    "closed_by_mt5_sync": True,
                    "close_deal_missing": True,
                    "close_reason": "Position was not present in MT5 positions_get() during sync",
                }

            position.status = "CLOSED"
            position.closed_at = position.closed_at or datetime.now(UTC)
            count += 1
        return count


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _calculate_position_profit(
    *,
    open_price: float,
    current_price: float,
    volume: float,
    side: str,
    contract_size: float,
) -> float:
    direction = 1 if side == "BUY" else -1
    return (current_price - open_price) * volume * contract_size * direction


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
    grouped: dict[int, list[dict[str, Any]]] = {}
    for deal in deals:
        position_id = _int_or_none(deal.get("position_id") or deal.get("position"))
        if position_id is None:
            continue
        grouped.setdefault(position_id, []).append(deal)
    return {
        position_id: _aggregate_position_deals(position_deals)
        for position_id, position_deals in grouped.items()
        if any(_is_close_deal(deal) for deal in position_deals)
    }


def _is_close_deal(deal: dict[str, Any]) -> bool:
    entry = _int_or_none(deal.get("entry"))
    return entry in {1, 2, 3} or entry is None


def _aggregate_position_deals(position_deals: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(position_deals, key=_deal_sort_key)
    close_deals = [deal for deal in ordered if _is_close_deal(deal)]
    if len(ordered) == 1:
        return ordered[0]

    last_deal = close_deals[-1] if close_deals else ordered[-1]
    close_price = _weighted_price(close_deals) or _float_or_none(last_deal.get("price"))
    return {
        **last_deal,
        "price": close_price,
        "profit": sum(_float_or_none(deal.get("profit")) or 0.0 for deal in ordered),
        "swap": sum(_float_or_none(deal.get("swap")) or 0.0 for deal in ordered),
        "commission": sum(_float_or_none(deal.get("commission")) or 0.0 for deal in ordered),
        "fee": sum(_float_or_none(deal.get("fee")) or 0.0 for deal in ordered),
        "raw": {
            "deals": [deal.get("raw") if isinstance(deal.get("raw"), dict) else deal for deal in ordered],
            "deals_count": len(ordered),
            "close_tickets": [
                _int_or_none(deal.get("ticket") or deal.get("deal"))
                for deal in close_deals
                if _int_or_none(deal.get("ticket") or deal.get("deal")) is not None
            ],
        },
    }


def _weighted_price(deals: list[dict[str, Any]]) -> float | None:
    weighted_total = 0.0
    volume_total = 0.0
    for deal in deals:
        price = _float_or_none(deal.get("price"))
        volume = _float_or_none(deal.get("volume"))
        if price is None or volume is None or volume <= 0:
            continue
        weighted_total += price * volume
        volume_total += volume
    if volume_total <= 0:
        return None
    return weighted_total / volume_total


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
