from pydantic import BaseModel, ConfigDict, Field


class SymbolMappingBase(BaseModel):
    internal_symbol: str = Field(min_length=3, max_length=32)
    broker_symbol: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    asset_class: str = Field(default="METAL", min_length=2, max_length=32)
    tradable: bool = True
    analysis_only: bool = False
    digits: int = Field(default=2, ge=0, le=10)
    point: float = Field(default=0.01, gt=0)
    contract_size: float = Field(default=100.0, gt=0)


class SymbolMappingCreate(SymbolMappingBase):
    pass


class SymbolMappingUpdate(BaseModel):
    broker_symbol: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    asset_class: str | None = Field(default=None, min_length=2, max_length=32)
    tradable: bool | None = None
    analysis_only: bool | None = None
    digits: int | None = Field(default=None, ge=0, le=10)
    point: float | None = Field(default=None, gt=0)
    contract_size: float | None = Field(default=None, gt=0)


class SymbolMappingRead(SymbolMappingBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
