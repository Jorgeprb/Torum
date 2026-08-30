from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.candles.models import Candle
from app.db.base import Base
from app.mt5.schemas import MT5AccountPayload, MT5StatusPayload
from app.mt5.status_store import mt5_status_store
from app.orders.models import Order  # noqa: F401
from app.positions.models import Position
from app.risk.stopout import StopOutLineService
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
from app.users.models import User  # noqa: F401


@pytest.fixture(autouse=True)
def _reset_status() -> None:
    mt5_status_store.update(MT5StatusPayload())
    yield
    mt5_status_store.update(MT5StatusPayload())


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    for symbol, currency in (("XAUUSD", "USD"), ("XAUEUR", "EUR")):
        db.add(
            SymbolMapping(
                internal_symbol=symbol,
                broker_symbol=symbol,
                display_name=symbol,
                enabled=True,
                asset_class="METAL",
                tradable=True,
                analysis_only=False,
                digits=2,
                point=0.01,
                contract_size=100.0,
                profit_currency=currency,
                risk_conversion_rate=1.0,
            )
        )
    db.commit()
    return db


def _status(*, equity: float = 10000.0, margin: float = 1000.0) -> None:
    mt5_status_store.update(
        MT5StatusPayload(
            connected_to_mt5=True,
            account_trade_mode="DEMO",
            account=MT5AccountPayload(
                login=123,
                server="Broker-Demo",
                currency="USD",
                balance=10000.0,
                equity=equity,
                margin=margin,
                margin_free=equity - margin,
                margin_level=equity / margin * 100,
                margin_so_mode=0,
                margin_so_call=100.0,
                margin_so_so=50.0,
                trade_mode="DEMO",
            ),
        )
    )


def _tick(db: Session, symbol: str, price: float) -> None:
    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    db.add(
        Tick(
            id=1 if symbol == "XAUUSD" else 2,
            time=now,
            time_msc=int(now.timestamp() * 1000),
            internal_symbol=symbol,
            broker_symbol=symbol,
            bid=price,
            ask=price + 0.2,
            last=price,
            volume=1.0,
            source="MT5",
        )
    )
    db.commit()


def _position(db: Session, symbol: str, price: float, *, volume: float = 1.0) -> None:
    db.add(
        Position(
            user_id=None,
            order_id=None,
            internal_symbol=symbol,
            broker_symbol=symbol,
            mode="DEMO",
            account_login=123,
            account_server="Broker-Demo",
            side="BUY",
            volume=volume,
            open_price=price,
            current_price=price,
            close_price=None,
            sl=None,
            tp=None,
            profit=0.0,
            swap=0.0,
            commission=0.0,
            fee=0.0,
            status="OPEN",
            mt5_position_ticket=1000 + (1 if symbol == "XAUUSD" else 2),
            opened_at=datetime(2026, 8, 27, 10, 0, tzinfo=UTC),
            raw_payload_json={},
        )
    )
    db.commit()


def test_stopout_line_uses_both_gold_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _session()
    _status()
    _tick(db, "XAUUSD", 2000.0)
    _tick(db, "XAUEUR", 1800.0)
    _position(db, "XAUUSD", 2000.0)
    _position(db, "XAUEUR", 1800.0)

    monkeypatch.setattr(StopOutLineService, "_profit_per_price_unit", lambda *args, **kwargs: 100.0)
    result = StopOutLineService(db).get_line("XAUUSD")

    assert result.visible is True
    # With beta fallback 1: Δequity = 100*dP + 100*(0.9*dP) = 190*dP.
    # Stop-out equity is 50% of 1000 margin = 500; 9500 must be lost.
    assert result.price == pytest.approx(1950.0, abs=0.02)
    assert result.correlated_other_symbol == "XAUEUR"
    assert result.projected_other_price == pytest.approx(1755.0, abs=0.03)


def test_stopout_line_hidden_without_position_on_viewed_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _session()
    _status()
    _tick(db, "XAUUSD", 2000.0)
    _tick(db, "XAUEUR", 1800.0)
    _position(db, "XAUEUR", 1800.0)
    monkeypatch.setattr(StopOutLineService, "_profit_per_price_unit", lambda *args, **kwargs: 100.0)

    result = StopOutLineService(db).get_line("XAUUSD")
    assert result.visible is False
    assert result.price is None


def test_h1_correlation_calculates_directional_betas(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _session()
    import math

    usd_closes: dict[datetime, float] = {}
    eur_closes: dict[datetime, float] = {}
    start = datetime(2026, 7, 1, tzinfo=UTC)
    usd = 2000.0
    eur = 1800.0
    for index in range(220):
        r_usd = (0.001 + (index % 7) * 0.0002) * (1 if index % 2 == 0 else -1)
        if index:
            usd *= math.exp(r_usd)
            eur *= math.exp(0.9 * r_usd)
        at = start + timedelta(hours=index)
        usd_closes[at] = usd
        eur_closes[at] = eur

    monkeypatch.setattr(
        StopOutLineService,
        "_h1_closes",
        lambda self, symbol: usd_closes if symbol == "XAUUSD" else eur_closes,
    )

    model = StopOutLineService(db)._correlation_model()
    assert model.source == "BROKER_H1_LOG_RETURNS"
    assert model.samples >= 200
    assert model.pearson == pytest.approx(1.0, abs=1e-9)
    assert model.beta_eur_from_usd == pytest.approx(0.9, abs=1e-6)
    assert model.beta_usd_from_eur == pytest.approx(1 / 0.9, abs=1e-6)
