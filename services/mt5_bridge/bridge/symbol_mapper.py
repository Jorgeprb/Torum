from dataclasses import dataclass
import logging

from bridge.config import BridgeSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SymbolMapping:
    internal_symbol: str
    broker_symbol: str
    display_name: str
    enabled: bool = True
    asset_class: str = "OTHER"
    tradable: bool = True
    analysis_only: bool = False
    digits: int = 2
    point: float = 0.01
    contract_size: float = 100.0


def parse_fallback_mappings(raw_value: str) -> list[SymbolMapping]:
    mappings: list[SymbolMapping] = []
    for item in raw_value.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            internal_symbol, broker_symbol = item.split(":", 1)
        elif "=" in item:
            internal_symbol, broker_symbol = item.split("=", 1)
        else:
            internal_symbol = broker_symbol = item
        mappings.append(
            SymbolMapping(
                internal_symbol=internal_symbol.strip().upper(),
                broker_symbol=broker_symbol.strip(),
                display_name=internal_symbol.strip().upper(),
            )
        )
    return mappings


class SymbolMapper:
    def __init__(self, settings: BridgeSettings) -> None:
        self.settings = settings

    def load(self, backend_symbols: list[dict[str, object]] | None) -> list[SymbolMapping]:
        mappings = self._from_backend(backend_symbols) if backend_symbols else []
        if not mappings:
            logger.warning("Using local fallback symbol mapping because backend symbols were not available")
            mappings = parse_fallback_mappings(self.settings.mt5_fallback_symbol_mappings)

        enabled_symbols = self.settings.enabled_internal_symbols
        if enabled_symbols is not None:
            mappings = [mapping for mapping in mappings if mapping.internal_symbol in enabled_symbols]

        return [mapping for mapping in mappings if mapping.enabled]

    def _from_backend(self, backend_symbols: list[dict[str, object]]) -> list[SymbolMapping]:
        mappings: list[SymbolMapping] = []
        for item in backend_symbols:
            if not item.get("enabled", True):
                continue
            mappings.append(
                SymbolMapping(
                    internal_symbol=str(item["internal_symbol"]).upper(),
                    broker_symbol=str(item["broker_symbol"]),
                    display_name=str(item.get("display_name") or item["internal_symbol"]),
                    enabled=bool(item.get("enabled", True)),
                    asset_class=str(item.get("asset_class") or "OTHER"),
                    tradable=bool(item.get("tradable", True)),
                    analysis_only=bool(item.get("analysis_only", False)),
                    digits=int(item.get("digits") or 2),
                    point=float(item.get("point") or 0.01),
                    contract_size=float(item.get("contract_size") or 100.0),
                )
            )
        return mappings
