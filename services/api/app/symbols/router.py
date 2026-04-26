from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.symbols.schemas import SymbolMappingCreate, SymbolMappingRead, SymbolMappingUpdate
from app.symbols.service import (
    create_symbol_mapping,
    get_symbol_mapping,
    list_symbol_mappings,
    update_symbol_mapping,
)

router = APIRouter(prefix="/symbols", tags=["symbols"])


@router.get("", response_model=list[SymbolMappingRead])
def list_symbols(db: Annotated[Session, Depends(get_db)]) -> list[SymbolMappingRead]:
    return [SymbolMappingRead.model_validate(mapping) for mapping in list_symbol_mappings(db)]


@router.post("", response_model=SymbolMappingRead, status_code=status.HTTP_201_CREATED)
def create_symbol(payload: SymbolMappingCreate, db: Annotated[Session, Depends(get_db)]) -> SymbolMappingRead:
    return SymbolMappingRead.model_validate(create_symbol_mapping(db, payload))


@router.patch("/{mapping_id}", response_model=SymbolMappingRead)
def update_symbol(
    mapping_id: int,
    payload: SymbolMappingUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> SymbolMappingRead:
    mapping = get_symbol_mapping(db, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol mapping not found")
    return SymbolMappingRead.model_validate(update_symbol_mapping(db, mapping, payload))
