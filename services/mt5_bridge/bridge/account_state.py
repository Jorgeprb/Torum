from dataclasses import asdict, dataclass
from typing import Any, Literal

AccountTradeMode = Literal["DEMO", "REAL", "UNKNOWN"]


@dataclass(slots=True)
class AccountState:
    login: int | None = None
    server: str | None = None
    name: str | None = None
    company: str | None = None
    currency: str | None = None
    balance: float | None = None
    equity: float | None = None
    margin: float | None = None
    margin_free: float | None = None
    leverage: int | None = None
    trade_mode: AccountTradeMode = "UNKNOWN"

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    if isinstance(value, dict):
        return value
    return {name: getattr(value, name) for name in dir(value) if not name.startswith("_")}


def detect_trade_mode(account_info: Any) -> AccountTradeMode:
    data = _as_mapping(account_info)
    raw_trade_mode = data.get("trade_mode")

    if raw_trade_mode in (0, "0", "DEMO", "ACCOUNT_TRADE_MODE_DEMO"):
        return "DEMO"
    if raw_trade_mode in (2, "2", "REAL", "ACCOUNT_TRADE_MODE_REAL"):
        return "REAL"

    text = " ".join(
        str(data.get(field) or "")
        for field in ("server", "name", "company")
    ).lower()
    if "demo" in text:
        return "DEMO"
    if "real" in text or "live" in text:
        return "REAL"
    return "UNKNOWN"


def account_state_from_mt5(account_info: Any) -> AccountState:
    data = _as_mapping(account_info)
    return AccountState(
        login=data.get("login"),
        server=data.get("server"),
        name=data.get("name"),
        company=data.get("company"),
        currency=data.get("currency"),
        balance=data.get("balance"),
        equity=data.get("equity"),
        margin=data.get("margin"),
        margin_free=data.get("margin_free"),
        leverage=data.get("leverage"),
        trade_mode=detect_trade_mode(data),
    )
