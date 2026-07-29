from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.candles.models import Candle
from app.db.base import Base
from app.drawings.models import ChartDrawing
from app.orders.models import Order
from app.strategies.schemas import TorumV1BacktestRequest
from app.strategies.service import StrategyCatalogService
from app.strategies.torum_v1_backtest import TorumV1BacktestCancelled, TorumV1BacktestEngine
from app.symbols.models import SymbolMapping
from app.users.models import User, UserRole


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = maker()
    db.add(User(id=1, username="admin", email="admin@example.com", hashed_password="x", role=UserRole.admin, is_active=True))
    db.add(SymbolMapping(internal_symbol="XAUUSD", broker_symbol="XAUUSD", display_name="XAUUSD", enabled=True, asset_class="METAL", tradable=True, analysis_only=False, digits=2, point=0.01, contract_size=100.0, risk_conversion_rate=1.0))
    start = datetime(2026, 1, 5, 8, 0)
    price = 2400.0
    for index in range(180):
        # Deterministic alternating candles; enough data to exercise the full engine.
        direction = -1 if index % 7 in {2, 3} else 1
        open_price = price
        close = open_price + direction * (0.8 + (index % 3) * 0.2)
        high = max(open_price, close) + 0.35
        low = min(open_price, close) - 0.35
        db.add(Candle(time=start + timedelta(minutes=5 * index), internal_symbol="XAUUSD", timeframe="M5", open=open_price, high=high, low=low, close=close, volume=1.0, tick_count=1, source="TEST"))
        db.flush()
        price = close
    db.commit()
    return db


def _config(db: Session):
    return StrategyCatalogService(db).update_torum_bundle(
        user_id=1,
        base_params={
            "enabled": True,
            "session_start": "00:00",
            "session_end": "23:59",
            "session_days": ["MO", "TU", "WE", "TH", "FR", "SA", "SU"],
            "pullback_entry_min_pct": 0.02,
            "require_zone": False,
            "usd_strength_filter_enabled": False,
            "take_profit_percent": 0.02,
            "suggested_volume": 0.01,
        },
        asset_overrides={},
        enabled_by_symbol={"XAUUSD": True},
        mode_by_symbol={"XAUUSD": "PAPER"},
        expected_revisions={},
        change_note="backtest test",
    )[1]


def test_backtest_is_side_effect_free_and_returns_metrics() -> None:
    db = _session()
    config = _config(db)
    request = TorumV1BacktestRequest(
        symbol="XAUUSD",
        candle_limit=180,
        use_session=False,
        use_unlock=False,
        use_news=False,
        use_dxy=False,
        use_operation_zones=False,
        use_supports=False,
        use_ath_capacity=False,
        use_risk=False,
        debug_level="FULL",
    )

    result = TorumV1BacktestEngine(db).run(config, request)

    assert result.symbol == "XAUUSD"
    assert result.candles_analyzed == 180
    assert result.metrics.initial_balance == 10000.0
    assert result.metrics.trading_days >= 1
    assert result.metrics.max_concurrent_trades >= 0
    assert result.coverage["orders"] == "never sent"
    assert result.elapsed_ms >= 0
    assert db.query(Order).count() == 0


def test_backtest_can_select_operation_regions_and_supports() -> None:
    db = _session()
    config = _config(db)
    first_time = int(db.query(Candle).order_by(Candle.time).first().time.replace(tzinfo=UTC).timestamp())
    db.add(
        ChartDrawing(
            id="zone-a",
            user_id=1,
            internal_symbol="XAUUSD",
            timeframe="M5",
            drawing_type="rectangle",
            name="Zona A",
            payload_json={"time1": first_time, "time2": first_time + 86400, "price1": 2300, "price2": 2500},
            style_json={},
            metadata_json={"torum_v1_zone_enabled": True, "direction": "BUY"},
            visible=True,
            source="MANUAL",
        )
    )
    db.add(
        ChartDrawing(
            id="support-a",
            user_id=1,
            internal_symbol="XAUUSD",
            timeframe="M5",
            drawing_type="horizontal_line",
            name="Soporte fuerte",
            payload_json={"price": 2400},
            style_json={},
            metadata_json={"supportLevel": 3, "supportLowerPrice": 2300, "supportUpperPrice": 2500, "enabled": True},
            visible=True,
            source="MANUAL",
        )
    )
    db.commit()

    request = TorumV1BacktestRequest(
        symbol="XAUUSD",
        candle_limit=180,
        use_session=False,
        use_unlock=False,
        use_news=False,
        use_dxy=False,
        use_operation_zones=True,
        use_supports=True,
        selected_operation_zone_ids=["zone-a"],
        selected_support_zone_ids=["support-a"],
        use_ath_capacity=False,
        use_risk=False,
    )
    result = TorumV1BacktestEngine(db).run(config, request)

    assert [item.id for item in result.operation_zones] == ["zone-a"]
    assert [item.id for item in result.supports] == ["support-a"]
    assert result.supports[0].level == 3


def test_backtest_respects_empty_zone_and_support_selection() -> None:
    db = _session()
    config = _config(db)
    first_time = int(db.query(Candle).order_by(Candle.time).first().time.replace(tzinfo=UTC).timestamp())
    db.add(
        ChartDrawing(
            id="zone-unselected",
            user_id=1,
            internal_symbol="XAUUSD",
            timeframe="M5",
            drawing_type="rectangle",
            name="Zona no seleccionada",
            payload_json={"time1": first_time, "time2": first_time + 86400, "price1": 2300, "price2": 2500},
            style_json={},
            metadata_json={"torum_v1_zone_enabled": True, "direction": "BUY"},
            visible=True,
            source="MANUAL",
        )
    )
    db.add(
        ChartDrawing(
            id="support-unselected",
            user_id=1,
            internal_symbol="XAUUSD",
            timeframe="M5",
            drawing_type="horizontal_line",
            name="Soporte no seleccionado",
            payload_json={"price": 2400},
            style_json={},
            metadata_json={"supportLevel": 3, "supportLowerPrice": 2300, "supportUpperPrice": 2500, "enabled": True},
            visible=True,
            source="MANUAL",
        )
    )
    db.commit()

    result = TorumV1BacktestEngine(db).run(
        config,
        TorumV1BacktestRequest(
            symbol="XAUUSD",
            candle_limit=180,
            use_session=False,
            use_unlock=False,
            use_news=False,
            use_dxy=False,
            use_operation_zones=True,
            use_supports=True,
            selected_operation_zone_ids=[],
            selected_support_zone_ids=[],
            use_ath_capacity=False,
            use_risk=False,
        ),
    )

    assert result.operation_zones == []
    assert result.supports == []
    assert any("ninguna región seleccionada" in warning for warning in result.warnings)
    assert any("sin soportes seleccionados" in warning for warning in result.warnings)


def test_backtest_drops_live_signal_deduplication_state() -> None:
    db = _session()
    config = _config(db)
    config.params_json = {
        **(config.params_json or {}),
        "last_signal_candle_time": 1,
        "last_signal_pullback_low_time": 1,
        "last_signal_operation_zone_id": "live-zone",
    }
    db.commit()

    result = TorumV1BacktestEngine(db).run(
        config,
        TorumV1BacktestRequest(
            symbol="XAUUSD",
            candle_limit=180,
            use_session=False,
            use_unlock=False,
            use_news=False,
            use_dxy=False,
            use_operation_zones=False,
            use_supports=False,
            use_ath_capacity=False,
            use_risk=False,
        ),
    )

    params = result.configuration["params"]
    assert "last_signal_candle_time" not in params
    assert "last_signal_pullback_low_time" not in params
    assert "last_signal_operation_zone_id" not in params


def test_backtest_reports_progress_and_can_be_cancelled() -> None:
    db = _session()
    config = _config(db)
    progress_values: list[float] = []
    cancelled = False

    def on_progress(progress: float, _stage: str, _message: str) -> None:
        nonlocal cancelled
        progress_values.append(progress)
        if progress >= 0.20:
            cancelled = True

    with pytest.raises(TorumV1BacktestCancelled):
        TorumV1BacktestEngine(db).run(
            config,
            TorumV1BacktestRequest(
                symbol="XAUUSD",
                candle_limit=180,
                use_session=False,
                use_unlock=False,
                use_news=False,
                use_dxy=False,
                use_operation_zones=False,
                use_supports=False,
                use_ath_capacity=False,
                use_risk=False,
            ),
            progress_callback=on_progress,
            cancel_check=lambda: cancelled,
        )

    assert progress_values
    assert progress_values == sorted(progress_values)
    assert max(progress_values) >= 0.20


def test_backtest_validates_real_entry_price_against_operation_rectangle() -> None:
    db = _session()
    config = _config(db)
    first_time = int(db.query(Candle).order_by(Candle.time).first().time.replace(tzinfo=UTC).timestamp())
    db.add(
        ChartDrawing(
            id="zone-entry-geometry",
            user_id=1,
            internal_symbol="XAUUSD",
            timeframe="M5",
            drawing_type="rectangle",
            name="Zona de ejecución",
            payload_json={
                "time1": first_time,
                "time2": first_time + 86400,
                "price1": 2300,
                "price2": 2500,
            },
            style_json={},
            metadata_json={"torum_v1_zone_enabled": True, "direction": "BUY"},
            visible=True,
            source="MANUAL",
        )
    )
    db.commit()

    base_params = {
        **(config.params_json or {}),
        "require_zone": True,
        "operation_zone_allow_confirmation_price_outside": False,
    }
    common_request = {
        "symbol": "XAUUSD",
        "candle_limit": 180,
        "use_session": False,
        "use_unlock": False,
        "use_news": False,
        "use_dxy": False,
        "use_operation_zones": True,
        "use_supports": False,
        "selected_operation_zone_ids": ["zone-entry-geometry"],
        "use_ath_capacity": False,
        "use_risk": False,
        "entry_model": "CONFIRMATION_CLOSE",
        # 10 000 points = 100.00 in this two-decimal test symbol. The
        # confirmation close can be inside while the executable ask is outside.
        "spread_points": 10000,
        "debug_level": "FULL",
    }

    strict = TorumV1BacktestEngine(db).run(
        config,
        TorumV1BacktestRequest(params=base_params, **common_request),
    )
    permissive = TorumV1BacktestEngine(db).run(
        config,
        TorumV1BacktestRequest(
            params={
                **base_params,
                "operation_zone_allow_confirmation_price_outside": True,
            },
            **common_request,
        ),
    )

    assert strict.metrics.rejection_counts.get("entry_price_outside_operation_zone", 0) > 0
    assert any(
        event.reason_code == "entry_price_outside_operation_zone"
        and event.details.get("entry_time_inside") is True
        and event.details.get("entry_price_inside") is False
        for event in strict.debug_events
    )
    assert permissive.metrics.rejection_counts.get("entry_price_outside_operation_zone", 0) == 0
    assert permissive.metrics.total_trades > strict.metrics.total_trades
