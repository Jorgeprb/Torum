from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.symbols.models import SymbolMapping
from app.symbols.schemas import SymbolMappingCreate, SymbolMappingUpdate

DEFAULT_SYMBOL_MAPPINGS: tuple[dict[str, object], ...] = (
    {
        "internal_symbol": "XAUUSD",
        "broker_symbol": "XAUUSD",
        "display_name": "Gold / USD",
        "enabled": True,
        "asset_class": "METAL",
        "tradable": True,
        "analysis_only": False,
        "digits": 2,
        "point": 0.01,
        "contract_size": 100.0,
    },
    {
        "internal_symbol": "XAUEUR",
        "broker_symbol": "XAUEUR",
        "display_name": "Gold / EUR",
        "enabled": True,
        "asset_class": "METAL",
        "tradable": True,
        "analysis_only": False,
        "digits": 2,
        "point": 0.01,
        "contract_size": 100.0,
    },
    {
        "internal_symbol": "XAUAUD",
        "broker_symbol": "XAUAUD",
        "display_name": "Gold / AUD",
        "enabled": True,
        "asset_class": "METAL",
        "tradable": True,
        "analysis_only": False,
        "digits": 2,
        "point": 0.01,
        "contract_size": 100.0,
    },
    {
        "internal_symbol": "XAUJPY",
        "broker_symbol": "XAUJPY",
        "display_name": "Gold / JPY",
        "enabled": True,
        "asset_class": "METAL",
        "tradable": True,
        "analysis_only": False,
        "digits": 2,
        "point": 0.01,
        "contract_size": 100.0,
    },
    {
        "internal_symbol": "DXY",
        "broker_symbol": "DXY",
        "display_name": "US Dollar Index",
        "enabled": True,
        "asset_class": "INDEX",
        "tradable": False,
        "analysis_only": True,
        "digits": 2,
        "point": 0.01,
        "contract_size": 1.0,
    },
)


def list_symbol_mappings(db: Session) -> list[SymbolMapping]:
    return list(db.scalars(select(SymbolMapping).order_by(SymbolMapping.internal_symbol)))


def get_symbol_mapping(db: Session, mapping_id: int) -> SymbolMapping | None:
    return db.get(SymbolMapping, mapping_id)


def get_symbol_by_internal(db: Session, internal_symbol: str) -> SymbolMapping | None:
    return db.scalar(select(SymbolMapping).where(SymbolMapping.internal_symbol == internal_symbol))


def enabled_internal_symbols(db: Session) -> set[str]:
    rows = db.scalars(select(SymbolMapping.internal_symbol).where(SymbolMapping.enabled.is_(True)))
    return set(rows)


def create_symbol_mapping(db: Session, payload: SymbolMappingCreate) -> SymbolMapping:
    mapping = SymbolMapping(**payload.model_dump())
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


def update_symbol_mapping(db: Session, mapping: SymbolMapping, payload: SymbolMappingUpdate) -> SymbolMapping:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(mapping, field, value)
    db.commit()
    db.refresh(mapping)
    return mapping


def seed_default_symbols() -> None:
    with SessionLocal() as db:
        existing_symbols = {
            row
            for row in db.scalars(
                select(SymbolMapping.internal_symbol).where(
                    SymbolMapping.internal_symbol.in_(
                        [str(mapping["internal_symbol"]) for mapping in DEFAULT_SYMBOL_MAPPINGS]
                    )
                )
            )
        }
        for mapping in DEFAULT_SYMBOL_MAPPINGS:
            if mapping["internal_symbol"] in existing_symbols:
                continue
            db.add(SymbolMapping(**mapping))
        db.commit()
