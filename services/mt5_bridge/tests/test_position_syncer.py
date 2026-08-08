from datetime import datetime
from types import SimpleNamespace

from bridge.position_syncer import _load_closed_deals, _position_to_payload


class FakeMT5:
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_INOUT = 2
    DEAL_ENTRY_OUT_BY = 3
    DEAL_TYPE_BUY = 0
    DEAL_TYPE_SELL = 1

    def history_deals_get(self, date_from: datetime, date_to: datetime):  # type: ignore[no-untyped-def]
        return [
            SimpleNamespace(ticket=10, position_id=100, entry=self.DEAL_ENTRY_IN, type=self.DEAL_TYPE_BUY, price=1.0, profit=0.0, time=1, time_msc=1000),
            SimpleNamespace(ticket=11, position_id=100, entry=self.DEAL_ENTRY_OUT, type=self.DEAL_TYPE_SELL, price=2.0, profit=3.0, swap=-0.1, commission=-0.2, time=2, time_msc=2000),
            SimpleNamespace(ticket=12, position_id=101, entry=self.DEAL_ENTRY_INOUT, type=self.DEAL_TYPE_SELL, price=2.5, profit=4.0, swap=0.0, commission=-0.2, time=3, time_msc=3000),
            SimpleNamespace(ticket=13, position_id=102, entry=self.DEAL_ENTRY_OUT_BY, type=self.DEAL_TYPE_BUY, price=3.0, profit=5.0, swap=0.0, commission=-0.2, time=4, time_msc=4000),
        ]


def test_load_closed_deals_keeps_trade_deals_for_position_grouping() -> None:
    deals = _load_closed_deals(FakeMT5(), lookback_days=14)

    assert [deal["ticket"] for deal in deals] == [10, 11, 12, 13]
    assert deals[0]["position_id"] == 100
    assert deals[0]["price"] == 1.0
    assert deals[0]["profit"] == 0.0
    assert deals[1]["swap"] == -0.1
    assert deals[1]["commission"] == -0.2


def test_position_payload_preserves_ticket_and_identifier() -> None:
    position = SimpleNamespace(ticket=111, identifier=222, type=0, symbol="XAUUSD")
    mt5 = SimpleNamespace(POSITION_TYPE_BUY=0)

    payload = _position_to_payload(position, mt5)

    assert payload["position_ticket"] == 111
    assert payload["position_identifier"] == 222
    assert payload["side"] == "BUY"


def test_history_chunk_failure_is_not_reported_as_authoritative_empty_history() -> None:
    from datetime import UTC, timedelta
    from bridge.position_syncer import PositionSyncer

    class FakeClient:
        mt5 = SimpleNamespace(DEAL_TYPE_BUY=0, DEAL_TYPE_SELL=1)

        def get_history_deals(self, date_from, date_to):  # type: ignore[no-untyped-def]
            return None

    settings = SimpleNamespace(
        mt5_startup_history_reconcile_enabled=False,
        mt5_startup_history_reconcile_delay_seconds=0,
        mt5_history_chunk_days=7,
    )
    syncer = PositionSyncer(settings, FakeClient(), SimpleNamespace())  # type: ignore[arg-type]

    deals, complete = syncer._load_history_deals_chunked(
        datetime.now(UTC) - timedelta(days=1),
        datetime.now(UTC),
    )

    assert deals == []
    assert complete is False


def test_broad_history_loader_includes_broker_clock_future_window() -> None:
    from datetime import UTC, timedelta

    class CapturingMT5(FakeMT5):
        def __init__(self) -> None:
            self.date_from: datetime | None = None
            self.date_to: datetime | None = None

        def history_deals_get(self, date_from: datetime, date_to: datetime):  # type: ignore[no-untyped-def]
            self.date_from = date_from
            self.date_to = date_to
            return []

    mt5 = CapturingMT5()
    before = datetime.now(UTC)
    _load_closed_deals(mt5, lookback_days=14, future_tolerance_hours=14)
    after = datetime.now(UTC)

    assert mt5.date_to is not None
    assert before + timedelta(hours=13, minutes=59) <= mt5.date_to
    assert mt5.date_to <= after + timedelta(hours=14, seconds=1)


def test_incremental_history_preserves_cash_movements_for_performance() -> None:
    from datetime import UTC, timedelta
    from bridge.position_syncer import PositionSyncer

    class CashFlowMT5:
        DEAL_TYPE_BUY = 0
        DEAL_TYPE_SELL = 1
        DEAL_TYPE_BALANCE = 2
        DEAL_TYPE_CREDIT = 3
        DEAL_TYPE_CHARGE = 15
        DEAL_TYPE_CORRECTION = 16
        DEAL_TYPE_BONUS = 17

    class FakeClient:
        mt5 = CashFlowMT5()

        def get_history_deals(self, date_from, date_to):  # type: ignore[no-untyped-def]
            return [
                SimpleNamespace(ticket=20, position_id=0, entry=0, type=2, price=0.0, profit=2500.0, time=10, time_msc=10000, comment="deposit"),
                SimpleNamespace(ticket=21, position_id=100, entry=0, type=0, price=4000.0, profit=0.0, time=11, time_msc=11000),
            ]

    settings = SimpleNamespace(
        mt5_startup_history_reconcile_enabled=False,
        mt5_startup_history_reconcile_delay_seconds=0,
        mt5_history_chunk_days=7,
    )
    syncer = PositionSyncer(settings, FakeClient(), SimpleNamespace())  # type: ignore[arg-type]
    events, complete = syncer._load_history_deals_chunked(
        datetime.now(UTC) - timedelta(days=1),
        datetime.now(UTC),
    )

    assert complete is True
    assert len(events) == 2
    cash = next(event for event in events if event["history_category"] == "cash_flow")
    assert cash["cash_flow_kind"] == "DEPOSIT"
    assert cash["profit"] == 2500.0
    assert cash["time_domain"] == "BROKER_CHART"
    trade = next(event for event in events if event["history_category"] == "trade")
    assert trade["position_id"] == 100
