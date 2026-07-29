import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.alerts.push import PushNotificationService
from app.core.config import get_settings
from app.mt5.schemas import MT5AccountPayload
from app.mt5.client import MT5BridgeClient, MT5BridgeClientError
from app.orders.models import Order
from app.positions.models import Position
from app.positions.schemas import PositionRead
from app.positions.repository import get_position, list_positions
from app.risk.snapshot import RiskSnapshotService
from app.settings.trading_service import get_global_trading_settings
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
from app.ticks.service import latest_tick_order_by
from app.trade_jobs.service import enqueue_trade_job
from app.trading.lot_sizing import calculate_buy_take_profit
from app.websockets.manager import market_ws_manager

logger = logging.getLogger(__name__)


class PositionService:
    def __init__(
        self,
        db: Session,
        mt5_client: MT5BridgeClient | None = None,
        background_tasks: BackgroundTasks | None = None,
    ) -> None:
        self.db = db
        self.mt5_client = mt5_client or MT5BridgeClient()
        self.background_tasks = background_tasks

    def list_with_prices(
        self,
        status: str | None = None,
        limit: int = 100,
        symbol: str | None = None,
        *,
        user_id: int | None = None,
        include_all_users: bool = True,
    ) -> list[Position]:
        positions = list_positions(
            self.db,
            status=status,
            limit=limit,
            symbol=symbol,
            user_id=user_id,
            include_all_users=include_all_users,
        )

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

    def close_position(self, position_id: int, *, fetch_close_deal: bool = False) -> tuple[bool, str, Position | None]:
        position = get_position(self.db, position_id)
        if position is None:
            return False, "Position not found", None
        if position.status != "OPEN":
            return False, "Position is not open", position

        if position.mode == "PAPER":
            self._update_position_price(position)
            position.status = "CLOSED"
            position.closed_at = datetime.now(UTC)
            position.close_time_msc = int(position.closed_at.timestamp() * 1000)
            position.close_price = position.current_price
            position.enrichment_status = "CONFIRMED"
            self.db.commit()
            self._schedule_position_event("position_closed", position)
            self._notify_take_profit_hit(position)
            self._schedule_post_close_tasks(position.id, None, None)
            return True, "Paper position closed", position

        if self._reconcile_already_closed_mt5_position(position, source="manual_close_preflight"):
            return True, "Position was already closed in MT5 and has been reconciled", position

        close_ticket = position.mt5_position_ticket or position.mt5_position_identifier
        if close_ticket is None:
            return False, "MT5 position ticket is missing", position

        try:
            response = self.mt5_client.close_position(
                close_ticket,
                {
                    "internal_symbol": position.internal_symbol,
                    "broker_symbol": position.broker_symbol,
                    "side": position.side,
                    "volume": position.volume,
                    "mode": position.mode,
                    "magic_number": position.magic_number,
                    "fetch_close_deal": fetch_close_deal,
                },
            )
        except MT5BridgeClientError as exc:
            return False, str(exc), position

        if not response.get("ok"):
            if self._reconcile_already_closed_mt5_position(position, source="manual_close_rejected"):
                return True, "Position was already closed in MT5 and has been reconciled", position
            return False, str(response.get("comment") or "MT5 close rejected"), position

        position.status = "CLOSED"
        close_deal = response.get("close_deal")
        if not isinstance(close_deal, dict):
            raw_payload = response.get("raw")
            close_deal = raw_payload.get("close_deal") if isinstance(raw_payload, dict) else None
        if isinstance(close_deal, dict):
            _apply_close_deal(position, close_deal)
        else:
            position.closed_at = datetime.now(UTC)
            position.close_time_msc = _int_or_none(response.get("time_msc")) or int(position.closed_at.timestamp() * 1000)
            position.close_price = _float_or_none(response.get("price")) or position.current_price
            position.enrichment_status = "PENDING_MT5_DEAL"
            position.current_price = position.close_price or position.current_price
            position.closing_deal_ticket = _int_or_none(response.get("deal"))
            position.close_payload_json = response
        position.raw_payload_json = {
            **(position.raw_payload_json or {}),
            "close_response": response,
            "close_enrichment_status": "UPDATED" if isinstance(close_deal, dict) else "PENDING",
        }
        self.db.commit()
        self._schedule_position_event("position_closed", position)
        self._notify_take_profit_hit(position)
        if not isinstance(close_deal, dict):
            self._schedule_post_close_tasks(
                position.id,
                position.mt5_position_identifier or position.mt5_position_ticket,
                position.closing_deal_ticket,
            )
        else:
            self._schedule_post_close_tasks(position.id, None, None)
        return True, "MT5 position closed", position

    def _reconcile_already_closed_mt5_position(self, position: Position, *, source: str) -> bool:
        """Close a stale Torum row only after MT5 authoritatively confirms absence.

        A take profit can close the broker position between two sync cycles.  A
        subsequent manual close then returns MT5's generic ``Invalid request``.
        Treating that response as a failed close leaves a ghost position in the
        UI.  This pre/post-flight reconciliation is deliberately conservative:
        MT5 health must be connected and the position must be absent from the
        current ``positions_get`` snapshot before Torum changes local state.
        """
        try:
            health = self.mt5_client.health()
            if not bool(health.get("connected_to_mt5")):
                return False
            open_positions = self.mt5_client.get_positions()
        except MT5BridgeClientError:
            return False

        if any(_mt5_position_matches_local(raw, position) for raw in open_positions):
            return False

        close_deal = self._fetch_close_deal_for_position(position)
        position.status = "CLOSED"
        position.missing_sync_count = 0
        if close_deal is not None:
            _apply_close_deal(position, close_deal)
        else:
            self._update_position_price(position)
            position.closed_at = position.closed_at or datetime.now(UTC)
            position.close_time_msc = position.close_time_msc or int(position.closed_at.timestamp() * 1000)
            position.close_price = position.close_price or position.current_price
            position.current_price = position.close_price or position.current_price
            position.enrichment_status = "PENDING_MT5_DEAL"
            position.sync_state = "CLOSED_BY_CONFIRMED_ABSENCE"
            identity = position.mt5_position_identifier or position.mt5_position_ticket
            if identity is not None:
                enqueue_trade_job(
                    self.db,
                    job_type="ENRICH_CLOSE",
                    idempotency_key=f"enrich-close:{position.id}:latest",
                    payload={"position_id": position.id, "ticket": identity, "deal_ticket": None},
                    reactivate_completed=True,
                )
        position.raw_payload_json = {
            **(position.raw_payload_json or {}),
            "closed_by_mt5_reconciliation": True,
            "close_reconciliation_source": source,
            "close_deal_missing": close_deal is None,
        }
        RiskSnapshotService(self.db).mark_dirty(position.internal_symbol)
        self.db.commit()
        self.db.refresh(position)
        self._schedule_position_event("position_closed", position)
        self._notify_take_profit_hit(position)
        return True

    def _fetch_close_deal_for_position(self, position: Position) -> dict[str, Any] | None:
        for identity in _position_mt5_identities(position):
            try:
                response = self.mt5_client.get_close_deal(identity)
            except MT5BridgeClientError:
                continue
            deal = response.get("close_deal") if isinstance(response, dict) else None
            if not isinstance(deal, dict) and isinstance(response, dict):
                raw = response.get("raw")
                deal = raw.get("close_deal") if isinstance(raw, dict) else None
            if isinstance(deal, dict):
                return deal
        return None

    def _schedule_position_event(self, event_type: str, position: Position) -> None:
        if self.background_tasks is None:
            return
        payload = PositionRead.model_validate(position).model_dump(mode="json")
        self.background_tasks.add_task(
            market_ws_manager.broadcast_position_event,
            {
                "type": event_type,
                "position_id": position.id,
                "symbol": position.internal_symbol,
                "position": payload,
                "source": "position_api",
            },
        )

    def reconcile_missing_mt5_positions(self) -> dict[str, int]:
        """Mark unresolved live positions for reconciliation without fabricating a close."""
        stmt = select(Position).where(
            Position.status == "OPEN",
            Position.mode != "PAPER",
            Position.mt5_position_ticket.is_(None),
        )
        unresolved = 0
        for position in self.db.scalars(stmt):
            position.sync_state = "UNRESOLVED_TICKET"
            position.raw_payload_json = {
                **(position.raw_payload_json or {}),
                "reconcile_warning": "Missing MT5 position ticket; position kept open until MT5 confirms state",
            }
            unresolved += 1
        self.db.commit()
        return {"closed": 0, "unresolved": unresolved}

    def close_all_paper(self) -> int:
        positions = self.list_with_prices(status="OPEN", limit=1000)
        changed_symbols: set[str] = set()
        count = 0
        for position in positions:
            if position.mode != "PAPER":
                continue
            position.status = "CLOSED"
            position.closed_at = datetime.now(UTC)
            position.close_price = position.current_price
            position.sync_state = "CLOSED_PAPER"
            changed_symbols.add(position.internal_symbol)
            count += 1
        for symbol in sorted(changed_symbols):
            RiskSnapshotService(self.db).mark_dirty(symbol)
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
    ) -> dict[str, Any]:
        account_login = account.login if account else None
        account_server = account.server if account else None
        mode = "LIVE" if account and account.trade_mode == "REAL" else "DEMO"
        seen_position_ids: set[int] = set()
        close_deals_by_position = _latest_close_deals_by_position(closed_deals or [])
        created = 0
        updated = 0
        risk_changed_symbols: set[str] = set()
        changed_positions: dict[int, Position] = {}

        for raw in positions:
            ticket = _int_or_none(
                raw.get("ticket")
                or raw.get("position_ticket")
                or raw.get("identifier")
                or raw.get("position_identifier")
            )
            if ticket is None:
                continue
            identifier = _int_or_none(raw.get("identifier") or raw.get("position_identifier")) or ticket
            seen_position_ids.update({ticket, identifier})
            broker_symbol = str(raw.get("symbol") or raw.get("broker_symbol") or "")
            if not broker_symbol:
                continue
            mapping = self.db.scalar(select(SymbolMapping).where(SymbolMapping.broker_symbol == broker_symbol).limit(1))
            internal_symbol = str(raw.get("internal_symbol") or (mapping.internal_symbol if mapping else broker_symbol)).upper()
            side = _side_from_mt5_position(raw)
            open_price = _float_or_none(raw.get("price_open") or raw.get("open_price")) or 0.0
            opened_at = _datetime_from_mt5_seconds(raw.get("time")) or datetime.now(UTC)
            if open_price <= 0:
                logger.error("mt5_position_invalid_open_price ticket=%s symbol=%s", ticket, broker_symbol)
                continue

            position_stmt = select(Position).where(
                or_(
                    Position.mt5_position_ticket == ticket,
                    Position.mt5_position_identifier == identifier,
                )
            )
            if account_login is not None:
                position_stmt = position_stmt.where(or_(Position.account_login == account_login, Position.account_login.is_(None)))
            if account_server:
                position_stmt = position_stmt.where(or_(Position.account_server == account_server, Position.account_server.is_(None)))
            position = self.db.scalar(position_stmt.order_by(Position.id.desc()).limit(1))
            matched_order = self._match_order_for_synced_mt5_position(
                internal_symbol=internal_symbol,
                broker_symbol=broker_symbol,
                side=side,
                volume=_float_or_none(raw.get("volume")) or 0.0,
                magic_number=_int_or_none(raw.get("magic")),
                opened_at=opened_at,
                account_login=account_login,
                account_server=account_server,
            )
            if position is None and matched_order is not None:
                position = self.db.scalar(
                    select(Position)
                    .where(Position.order_id == matched_order.id, Position.status == "OPEN")
                    .order_by(Position.id.desc())
                    .limit(1)
                )
                if position is not None:
                    position.mt5_position_ticket = ticket
                    position.mt5_position_identifier = identifier

            raw_tp = _float_or_none(raw.get("tp"))
            intended_tp = self._intended_synced_position_tp(
                raw=raw,
                order=matched_order,
                side=side,
                open_price=open_price,
            )

            if position is None:
                position = Position(
                    user_id=matched_order.user_id if matched_order else None,
                    order_id=matched_order.id if matched_order else None,
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
                    tp=intended_tp if intended_tp is not None else raw_tp,
                    profit=_float_or_none(raw.get("profit")),
                    status="OPEN",
                    mt5_position_ticket=ticket,
                    mt5_position_identifier=identifier,
                    magic_number=_int_or_none(raw.get("magic")),
                    opened_at=opened_at,
                    open_time_msc=_mt5_time_msc(raw),
                    enrichment_status="OPEN_CONFIRMED",
                    missing_sync_count=0,
                    last_seen_mt5_at=datetime.now(UTC),
                    sync_state="CONFIRMED",
                    raw_payload_json=raw,
                )
                self.db.add(position)
                self.db.flush()
                created += 1
                changed_positions[position.id] = position
                risk_changed_symbols.add(internal_symbol)
            else:
                visual_before = _position_visual_snapshot(position)
                risk_before = _position_risk_snapshot(position)

                if position.order_id is None and matched_order is not None:
                    position.order_id = matched_order.id
                    position.user_id = matched_order.user_id
                position.internal_symbol = internal_symbol
                position.broker_symbol = broker_symbol
                position.mode = mode
                position.account_login = account_login or position.account_login
                position.account_server = account_server or position.account_server
                position.side = side
                position.mt5_position_ticket = ticket
                position.mt5_position_identifier = identifier
                position.volume = _float_or_none(raw.get("volume")) or position.volume
                # positions_get() is authoritative: replace provisional Torum values.
                position.open_price = open_price
                position.opened_at = opened_at
                position.open_time_msc = _mt5_time_msc(raw)
                position.enrichment_status = "OPEN_CONFIRMED"
                # The broker remains the source of truth for live valuation.
                current_price = _float_or_none(raw.get("price_current"))
                if current_price is not None:
                    position.current_price = current_price
                position.sl = _float_or_none(raw.get("sl"))
                position.tp = intended_tp if intended_tp is not None else raw_tp
                position.profit = _float_or_none(raw.get("profit"))
                position.missing_sync_count = 0
                position.last_seen_mt5_at = datetime.now(UTC)
                position.sync_state = "CONFIRMED"

                # An authoritative positions_get row means the position is open.
                position.status = "OPEN"
                position.closed_at = None
                position.close_price = None
                position.closing_deal_ticket = None
                position.close_payload_json = None
                position.raw_payload_json = {
                    **(position.raw_payload_json or {}),
                    "mt5_open_position": raw,
                }

                if _position_visual_snapshot(position) != visual_before:
                    updated += 1
                    changed_positions[position.id] = position
                if _position_risk_snapshot(position) != risk_before:
                    risk_changed_symbols.add(internal_symbol)

            if matched_order is not None:
                self._mark_synced_order_executed(matched_order, position, raw, open_price, opened_at, intended_tp)
            self._repair_synced_position_tp(position, matched_order, raw, intended_tp)

        refreshed, refreshed_symbols, refreshed_positions = self._refresh_closed_mt5_position_deals(
            close_deals_by_position,
            account_login=account_login,
            account_server=account_server,
        )
        updated += refreshed
        risk_changed_symbols.update(refreshed_symbols)
        changed_positions.update({position.id: position for position in refreshed_positions})

        closed, closed_symbols, closed_positions = self._close_missing_mt5_positions(
            seen_position_ids,
            account_login=account_login,
            account_server=account_server,
            close_deals_by_position=close_deals_by_position,
        )
        risk_changed_symbols.update(closed_symbols)
        changed_positions.update({position.id: position for position in closed_positions})

        snapshot_service = RiskSnapshotService(self.db)
        for symbol in sorted(risk_changed_symbols):
            snapshot_service.mark_dirty(symbol)
        self.db.flush()
        changed_payloads = [
            PositionRead.model_validate(position).model_dump(mode="json")
            for position in sorted(changed_positions.values(), key=lambda item: item.id)
        ]
        self.db.commit()
        return {
            "created": created,
            "updated": updated,
            "closed": closed,
            "received": len(positions),
            "deals_received": len(closed_deals or []),
            "changed_positions": changed_payloads,
        }

    def _match_order_for_synced_mt5_position(
        self,
        *,
        internal_symbol: str,
        broker_symbol: str,
        side: str,
        volume: float,
        magic_number: int | None,
        opened_at: datetime,
        account_login: int | None,
        account_server: str | None,
    ) -> Order | None:
        # Never match a live MT5 position to an arbitrary order from hours ago.
        # A small, account-scoped window prevents two same-volume entries from
        # stealing each other's ticket while still tolerating clock skew.
        window_start = opened_at - timedelta(minutes=5)
        window_end = opened_at + timedelta(minutes=5)
        stmt = select(Order).where(
            Order.internal_symbol == internal_symbol,
            Order.broker_symbol == broker_symbol,
            Order.side == side,
            Order.mt5_position_ticket.is_(None),
            Order.status.in_(["CREATED", "VALIDATING", "SENT", "EXECUTED"]),
            Order.created_at >= window_start,
            Order.created_at <= window_end,
        )
        if account_login is not None:
            stmt = stmt.where(or_(Order.account_login == account_login, Order.account_login.is_(None)))
        if account_server:
            stmt = stmt.where(or_(Order.account_server == account_server, Order.account_server.is_(None)))
        candidates = self.db.scalars(stmt.order_by(Order.created_at.desc(), Order.id.desc()).limit(20)).all()

        compatible: list[Order] = []
        for order in candidates:
            if magic_number is not None and order.magic_number is not None and order.magic_number != magic_number:
                continue
            if abs(float(order.volume) - float(volume)) > max(0.000001, float(volume) * 0.001):
                continue
            compatible.append(order)
        if not compatible:
            return None
        opened_at_utc = _as_utc_datetime(opened_at)
        return min(
            compatible,
            key=lambda order: abs((_as_utc_datetime(order.created_at) - opened_at_utc).total_seconds()),
        )

    def _intended_synced_position_tp(
        self,
        *,
        raw: dict[str, Any],
        order: Order | None,
        side: str,
        open_price: float,
    ) -> float | None:
        raw_tp = _float_or_none(raw.get("tp"))
        if raw_tp is not None and raw_tp > 0:
            return raw_tp
        if order is not None and order.tp is not None and order.tp > 0:
            return order.tp
        comment = str(raw.get("comment") or "").lower()
        if "strategy" not in comment or open_price <= 0:
            return raw_tp
        settings = get_global_trading_settings(self.db)
        tp_percent = _float_or_none(getattr(settings, "default_take_profit_percent", None)) or 0.09
        if side == "BUY":
            return calculate_buy_take_profit(open_price, tp_percent)
        return round(open_price * (1 - tp_percent / 100), 8)

    def _mark_synced_order_executed(
        self,
        order: Order,
        position: Position,
        raw: dict[str, Any],
        open_price: float,
        opened_at: datetime,
        intended_tp: float | None,
    ) -> None:
        order.status = "EXECUTED"
        order.executed_at = opened_at
        order.executed_price = open_price
        order.mt5_position_ticket = position.mt5_position_ticket
        if intended_tp is not None and intended_tp > 0:
            order.tp = intended_tp
        order.response_payload_json = {
            **(order.response_payload_json or {}),
            "mt5_open_position": raw,
            "position_resolved_by": "positions_sync",
            "tp_final": intended_tp,
            "tp_status": "PENDING" if intended_tp else (order.response_payload_json or {}).get("tp_status", "NONE"),
        }

    def _repair_synced_position_tp(
        self,
        position: Position,
        order: Order | None,
        raw: dict[str, Any],
        intended_tp: float | None,
    ) -> None:
        raw_tp = _float_or_none(raw.get("tp"))
        if intended_tp is None or intended_tp <= 0 or (raw_tp is not None and raw_tp > 0):
            return
        if position.mt5_position_ticket is None or position.mode == "PAPER" or order is None:
            return
        position.tp = intended_tp
        position.raw_payload_json = {
            **(position.raw_payload_json or raw),
            "tp_status": "PENDING",
            "tp_repair_source": "positions_sync",
        }
        order.tp = intended_tp
        order.response_payload_json = {
            **(order.response_payload_json or {}),
            "tp_status": "PENDING",
            "tp_repair_source": "positions_sync",
        }
        enqueue_trade_job(
            self.db,
            job_type="APPLY_TP",
            idempotency_key=f"apply-tp:{position.id}:{intended_tp:.8f}",
            payload={"position_id": position.id, "order_id": order.id, "final_tp": intended_tp},
            reactivate_completed=False,
        )

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

    def _refresh_risk_snapshot(self, symbol: str) -> None:
        try:
            RiskSnapshotService(self.db).mark_dirty(symbol)
        except Exception:  # noqa: BLE001
            logger.exception("risk_snapshot_mark_dirty_failed symbol=%s", symbol)

    def _schedule_post_close_tasks(self, position_id: int, ticket: int | None, deal: int | None) -> None:
        position = self.db.get(Position, position_id)
        if position is None:
            return
        if ticket is not None:
            enqueue_trade_job(
                self.db,
                job_type="ENRICH_CLOSE",
                idempotency_key=f"enrich-close:{position_id}:{deal or 'latest'}",
                payload={"position_id": position_id, "ticket": ticket, "deal_ticket": deal},
                reactivate_completed=False,
            )
        RiskSnapshotService(self.db).mark_dirty(position.internal_symbol)
        self.db.commit()

    def _notify_take_profit_hit(self, position: Position) -> None:
        if position.user_id is None or not _is_take_profit_hit(position):
            return
        payload = position.raw_payload_json or {}
        if payload.get("take_profit_push_sent_at"):
            return
        try:
            sent, _failed = PushNotificationService(self.db).send_take_profit_hit(
                position.user_id,
                symbol=position.internal_symbol,
                volume=float(position.volume),
                close_price=position.close_price,
                profit=position.profit,
                position_id=position.id,
            )
            if sent > 0:
                position.raw_payload_json = {
                    **payload,
                    "take_profit_push_sent_at": datetime.now(UTC).isoformat(),
                }
                self.db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("take_profit_push_failed position_id=%s", position.id)


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
    ) -> tuple[int, set[str], list[Position]]:
        if not close_deals_by_position:
            return 0, set(), []

        stmt = select(Position).where(
            Position.status == "CLOSED",
            or_(
                Position.mt5_position_ticket.in_(list(close_deals_by_position.keys())),
                Position.mt5_position_identifier.in_(list(close_deals_by_position.keys())),
            ),
        )
        if account_login is not None:
            stmt = stmt.where(or_(Position.account_login == account_login, Position.account_login.is_(None)))
        if account_server:
            stmt = stmt.where(or_(Position.account_server == account_server, Position.account_server.is_(None)))

        count = 0
        changed_symbols: set[str] = set()
        closed_positions: list[Position] = []
        for position in self.db.scalars(stmt):
            close_deal = _close_deal_for_position(position, close_deals_by_position)
            if close_deal is None:
                continue
            before = _position_close_snapshot(position)
            _apply_close_deal(position, close_deal)
            if _position_close_snapshot(position) == before:
                continue
            closed_positions.append(position)
            changed_symbols.add(position.internal_symbol)
            count += 1
        for position in closed_positions:
            self._notify_take_profit_hit(position)
        return count, changed_symbols, closed_positions


    def _close_missing_mt5_positions(
        self,
        seen_position_ids: set[int],
        *,
        account_login: int | None,
        account_server: str | None,
        close_deals_by_position: dict[int, dict[str, Any]],
    ) -> tuple[int, set[str], list[Position]]:
        stmt = select(Position).where(
            Position.status == "OPEN",
            or_(
                Position.mt5_position_ticket.is_not(None),
                Position.mt5_position_identifier.is_not(None),
            ),
        )
        if account_login is not None:
            stmt = stmt.where(or_(Position.account_login == account_login, Position.account_login.is_(None)))
        if account_server:
            stmt = stmt.where(or_(Position.account_server == account_server, Position.account_server.is_(None)))
        confirmations = max(2, get_settings().mt5_missing_position_confirmations)
        count = 0
        changed_symbols: set[str] = set()
        closed_positions: list[Position] = []
        for position in self.db.scalars(stmt):
            identities = _position_mt5_identities(position)
            ticket = position.mt5_position_ticket or position.mt5_position_identifier
            if any(identity in seen_position_ids for identity in identities):
                position.missing_sync_count = 0
                position.sync_state = "CONFIRMED"
                position.last_seen_mt5_at = datetime.now(UTC)
                continue
            close_deal = _close_deal_for_position(position, close_deals_by_position)
            if close_deal is not None:
                _apply_close_deal(position, close_deal)
                position.status = "CLOSED"
                position.missing_sync_count = 0
                position.sync_state = "CLOSED_CONFIRMED"
                closed_positions.append(position)
                changed_symbols.add(position.internal_symbol)
                count += 1
                continue

            position.missing_sync_count = int(position.missing_sync_count or 0) + 1
            position.sync_state = "MISSING_PENDING"
            position.raw_payload_json = {
                **(position.raw_payload_json or {}),
                "mt5_missing_sync_count": position.missing_sync_count,
                "mt5_missing_confirmations_required": confirmations,
            }
            if position.missing_sync_count < confirmations:
                logger.warning(
                    "mt5_position_missing_pending position_id=%s ticket=%s count=%s/%s",
                    position.id, ticket, position.missing_sync_count, confirmations,
                )
                continue

            self._update_position_price(position)
            position.close_price = position.current_price
            position.status = "CLOSED"
            position.closed_at = position.closed_at or datetime.now(UTC)
            position.close_time_msc = position.close_time_msc or int(position.closed_at.timestamp() * 1000)
            position.enrichment_status = "PENDING_MT5_DEAL"
            position.sync_state = "CLOSED_BY_CONFIRMED_ABSENCE"
            position.raw_payload_json = {
                **(position.raw_payload_json or {}),
                "closed_by_mt5_sync": True,
                "close_deal_missing": True,
                "close_reason": f"Position absent from {confirmations} consecutive authoritative positions_get snapshots",
            }
            enrichment_identity = position.mt5_position_identifier or ticket
            if enrichment_identity is not None:
                enqueue_trade_job(
                    self.db,
                    job_type="ENRICH_CLOSE",
                    idempotency_key=f"enrich-close:{position.id}:latest",
                    payload={"position_id": position.id, "ticket": enrichment_identity, "deal_ticket": None},
                    reactivate_completed=True,
                )
            closed_positions.append(position)
            changed_symbols.add(position.internal_symbol)
            count += 1
        for position in closed_positions:
            self._notify_take_profit_hit(position)
        return count, changed_symbols, closed_positions


def _stable_float(value: float | None, *, digits: int = 8) -> float | None:
    return None if value is None else round(float(value), digits)


def _position_visual_snapshot(position: Position) -> tuple[object, ...]:
    return (
        position.status,
        position.order_id,
        position.side,
        _stable_float(position.volume),
        _stable_float(position.open_price),
        _stable_float(position.current_price),
        _stable_float(position.sl),
        _stable_float(position.tp),
        _stable_float(position.profit),
        position.mt5_position_ticket,
        position.mt5_position_identifier,
        position.closed_at,
        _stable_float(position.close_price),
    )


def _position_risk_snapshot(position: Position) -> tuple[object, ...]:
    # Current market price and floating profit do not change exposure at the
    # configured ATH stress price, so they must not trigger a recomputation.
    return (
        position.status,
        position.order_id,
        position.internal_symbol,
        position.side,
        _stable_float(position.volume),
        _stable_float(position.open_price),
        position.account_login,
        position.account_server,
    )


def _position_close_snapshot(position: Position) -> tuple[object, ...]:
    return (
        position.status,
        position.closed_at,
        _stable_float(position.close_price),
        _stable_float(position.profit),
        _stable_float(position.swap),
        _stable_float(position.commission),
        _stable_float(position.fee),
        position.closing_deal_ticket,
    )


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


def _is_take_profit_hit(position: Position) -> bool:
    if position.tp is None or position.close_price is None:
        return False
    tolerance = max(abs(position.tp) * 0.00002, 0.02)
    if position.side == "BUY":
        return position.close_price >= position.tp - tolerance
    return position.close_price <= position.tp + tolerance



def _as_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _position_mt5_identities(position: Position) -> tuple[int, ...]:
    identities: list[int] = []
    for value in (position.mt5_position_identifier, position.mt5_position_ticket):
        if value is not None and int(value) not in identities:
            identities.append(int(value))
    payload = position.raw_payload_json if isinstance(position.raw_payload_json, dict) else {}
    for candidate in _known_mt5_identity_payloads(payload):
        for key in ("identifier", "position_identifier", "position_id", "ticket", "position_ticket"):
            value = _int_or_none(candidate.get(key))
            if value is not None and value not in identities:
                identities.append(value)
    return tuple(identities)


def _known_mt5_identity_payloads(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    candidates: list[dict[str, Any]] = [payload]
    for key in ("resolved_position_snapshot", "mt5_open_position", "close_response", "raw"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
            for nested_key in ("resolved_position_snapshot", "mt5_open_position"):
                nested_payload = nested.get(nested_key)
                if isinstance(nested_payload, dict):
                    candidates.append(nested_payload)
    return tuple(candidates)


def _mt5_position_matches_local(raw: dict[str, Any], position: Position) -> bool:
    raw_identities = {
        identity
        for identity in (
            _int_or_none(raw.get("ticket")),
            _int_or_none(raw.get("identifier")),
            _int_or_none(raw.get("position_ticket")),
            _int_or_none(raw.get("position_identifier")),
        )
        if identity is not None
    }
    return bool(raw_identities.intersection(_position_mt5_identities(position)))


def _close_deal_for_position(
    position: Position,
    close_deals_by_position: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    for identity in _position_mt5_identities(position):
        close_deal = close_deals_by_position.get(identity)
        if close_deal is not None:
            return close_deal
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


def _mt5_time_msc(raw: dict[str, Any]) -> int | None:
    value = _int_or_none(raw.get("time_msc"))
    if value is not None and value > 0:
        return value
    seconds = _int_or_none(raw.get("time"))
    return seconds * 1000 if seconds is not None and seconds > 0 else None


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
    return entry in {1, 2, 3}


def _aggregate_position_deals(position_deals: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(position_deals, key=_deal_sort_key)
    entry_deals = [deal for deal in ordered if _int_or_none(deal.get("entry")) == 0]
    close_deals = [deal for deal in ordered if _is_close_deal(deal)]
    last_deal = close_deals[-1] if close_deals else ordered[-1]
    first_entry = entry_deals[0] if entry_deals else ordered[0]
    entry_price = _weighted_price(entry_deals) or _float_or_none(first_entry.get("price"))
    close_price = _weighted_price(close_deals) or _float_or_none(last_deal.get("price"))
    entry_time_msc = _deal_sort_key(first_entry)[0]
    close_time_msc = _deal_sort_key(last_deal)[0]
    return {
        **last_deal,
        "price": close_price,
        "entry_price": entry_price,
        "entry_time_msc": entry_time_msc,
        "entry_time": entry_time_msc // 1000 if entry_time_msc else None,
        "close_time_msc": close_time_msc,
        "close_time": close_time_msc // 1000 if close_time_msc else None,
        "profit": sum(_float_or_none(deal.get("profit")) or 0.0 for deal in ordered),
        "swap": sum(_float_or_none(deal.get("swap")) or 0.0 for deal in ordered),
        "commission": sum(_float_or_none(deal.get("commission")) or 0.0 for deal in ordered),
        "fee": sum(_float_or_none(deal.get("fee")) or 0.0 for deal in ordered),
        "raw": {
            "deals": [deal.get("raw") if isinstance(deal.get("raw"), dict) else deal for deal in ordered],
            "deals_count": len(ordered),
            "entry_tickets": [
                _int_or_none(deal.get("ticket") or deal.get("deal"))
                for deal in entry_deals
                if _int_or_none(deal.get("ticket") or deal.get("deal")) is not None
            ],
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
    close_time_msc = _int_or_none(deal.get("close_time_msc") or deal.get("time_msc"))
    close_time = (
        _datetime_from_mt5_milliseconds(close_time_msc)
        if close_time_msc is not None
        else _datetime_from_mt5_seconds(deal.get("close_time") or deal.get("time"))
    )
    entry_time_msc = _int_or_none(deal.get("entry_time_msc"))
    entry_time = (
        _datetime_from_mt5_milliseconds(entry_time_msc)
        if entry_time_msc is not None
        else _datetime_from_mt5_seconds(deal.get("entry_time"))
    )
    entry_price = _float_or_none(deal.get("entry_price"))
    close_price = _float_or_none(deal.get("price"))
    if entry_price is not None and entry_price > 0:
        position.open_price = entry_price
    if entry_time is not None:
        position.opened_at = entry_time
    if entry_time_msc is not None:
        position.open_time_msc = entry_time_msc
    position.closed_at = close_time or position.closed_at or datetime.now(UTC)
    position.close_time_msc = close_time_msc or int(position.closed_at.timestamp() * 1000)
    position.close_price = close_price or position.close_price or position.current_price
    position.current_price = position.close_price or position.current_price
    position.profit = _float_or_none(deal.get("profit")) if deal.get("profit") is not None else position.profit
    position.swap = _float_or_none(deal.get("swap"))
    position.commission = _float_or_none(deal.get("commission"))
    position.fee = _float_or_none(deal.get("fee"))
    position.closing_deal_ticket = _int_or_none(deal.get("ticket") or deal.get("deal"))
    aggregate_raw = deal.get("raw") if isinstance(deal.get("raw"), dict) else None
    close_payload: dict[str, Any] | None = None
    if isinstance(aggregate_raw, dict):
        raw_deals = aggregate_raw.get("deals")
        if isinstance(raw_deals, list) and raw_deals:
            close_candidates = [item for item in raw_deals if isinstance(item, dict) and _is_close_deal(item)]
            last_raw = (close_candidates or [item for item in raw_deals if isinstance(item, dict)])[-1]
            close_payload = last_raw
        elif "ticket" in aggregate_raw or "position_id" in aggregate_raw:
            close_payload = aggregate_raw
    position.close_payload_json = close_payload or deal
    position.missing_sync_count = 0
    position.sync_state = "CLOSED_CONFIRMED"
    position.enrichment_status = "CONFIRMED_MT5"
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
