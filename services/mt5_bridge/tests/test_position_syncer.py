from datetime import datetime
from types import SimpleNamespace

from bridge.position_syncer import _load_closed_deals


class FakeMT5:
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_INOUT = 2
    DEAL_ENTRY_OUT_BY = 3

    def history_deals_get(self, date_from: datetime, date_to: datetime):  # type: ignore[no-untyped-def]
        return [
            SimpleNamespace(ticket=10, position_id=100, entry=self.DEAL_ENTRY_IN, price=1.0, profit=0.0, time=1, time_msc=1000),
            SimpleNamespace(ticket=11, position_id=100, entry=self.DEAL_ENTRY_OUT, price=2.0, profit=3.0, swap=-0.1, commission=-0.2, time=2, time_msc=2000),
            SimpleNamespace(ticket=12, position_id=101, entry=self.DEAL_ENTRY_INOUT, price=2.5, profit=4.0, swap=0.0, commission=-0.2, time=3, time_msc=3000),
            SimpleNamespace(ticket=13, position_id=102, entry=self.DEAL_ENTRY_OUT_BY, price=3.0, profit=5.0, swap=0.0, commission=-0.2, time=4, time_msc=4000),
        ]


def test_load_closed_deals_filters_mt5_close_entries() -> None:
    deals = _load_closed_deals(FakeMT5(), lookback_days=14)

    assert [deal["ticket"] for deal in deals] == [11, 12, 13]
    assert deals[0]["position_id"] == 100
    assert deals[0]["price"] == 2.0
    assert deals[0]["profit"] == 3.0
    assert deals[0]["swap"] == -0.1
    assert deals[0]["commission"] == -0.2
