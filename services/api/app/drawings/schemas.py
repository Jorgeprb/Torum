from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.drawings.validators import DRAWING_SOURCES, DRAWING_TYPES, normalize_style, validate_drawing_payload

DrawingType = Literal["horizontal_line", "vertical_line", "trend_line", "rectangle", "text", "manual_zone"]
DrawingSource = Literal["MANUAL", "INDICATOR", "NEWS", "STRATEGY", "IMPORT"]


class ChartDrawingCreate(BaseModel):
    internal_symbol: str = Field(min_length=3, max_length=32)
    timeframe: str | None = Field(default=None, max_length=8)
    drawing_type: str = Field(min_length=3, max_length=40)
    name: str | None = Field(default=None, max_length=160)
    payload: dict[str, Any]
    style: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    locked: bool = False
    visible: bool = True
    source: str = Field(default="MANUAL", max_length=40)

    @model_validator(mode="after")
    def normalize_and_validate(self) -> "ChartDrawingCreate":
        self.internal_symbol = self.internal_symbol.upper()
        self.drawing_type = self.drawing_type.lower()
        self.source = self.source.upper()
        if self.drawing_type not in DRAWING_TYPES:
            raise ValueError("Unsupported drawing_type")
        if self.source not in DRAWING_SOURCES:
            raise ValueError("Unsupported source")
        self.payload = validate_drawing_payload(self.drawing_type, self.payload)
        self.style = normalize_style(self.style)
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be an object")
        if self.name is not None:
            self.name = self.name.strip() or None
        return self


class ChartDrawingUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    payload: dict[str, Any] | None = None
    style: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    locked: bool | None = None
    visible: bool | None = None


class ChartDrawingRead(BaseModel):
    id: str
    user_id: int
    internal_symbol: str
    timeframe: str | None
    drawing_type: str
    name: str | None
    payload: dict[str, Any]
    style: dict[str, Any]
    metadata: dict[str, Any]
    locked: bool
    visible: bool
    source: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChartDrawingBulkCreate(BaseModel):
    items: list[ChartDrawingCreate] = Field(min_length=1, max_length=100)
