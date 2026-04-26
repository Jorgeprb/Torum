from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.drawings.models import ChartDrawing
from app.drawings.repository import list_drawings
from app.drawings.schemas import ChartDrawingCreate, ChartDrawingRead, ChartDrawingUpdate
from app.drawings.validators import normalize_style, validate_drawing_payload
from app.market_data.timeframes import Timeframe
from app.symbols.models import SymbolMapping
from app.users.models import User, UserRole


class ChartDrawingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_user(
        self,
        *,
        user: User,
        symbol: str,
        timeframe: Timeframe,
        include_hidden: bool = False,
    ) -> list[ChartDrawing]:
        return list_drawings(
            self.db,
            user_id=user.id,
            symbol=symbol,
            timeframe=timeframe,
            include_hidden=include_hidden,
        )

    def list_visible_for_overlays(self, *, user: User | None, symbol: str, timeframe: Timeframe) -> list[ChartDrawing]:
        if user is None:
            return []
        return list_drawings(
            self.db,
            user_id=user.id,
            symbol=symbol,
            timeframe=timeframe,
            visible_only=True,
        )

    def create(self, payload: ChartDrawingCreate, user: User) -> ChartDrawing:
        self._ensure_can_mutate(user)
        self._ensure_symbol_exists(payload.internal_symbol)
        if user.role != UserRole.admin and (payload.locked or payload.source != "MANUAL"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin can create locked or non-manual drawings",
            )
        drawing = ChartDrawing(
            user_id=user.id,
            internal_symbol=payload.internal_symbol,
            timeframe=payload.timeframe,
            drawing_type=payload.drawing_type,
            name=payload.name,
            payload_json=payload.payload,
            style_json=payload.style,
            metadata_json=payload.metadata,
            locked=payload.locked,
            visible=payload.visible,
            source=payload.source,
        )
        self.db.add(drawing)
        self.db.commit()
        self.db.refresh(drawing)
        return drawing

    def update(self, drawing: ChartDrawing, payload: ChartDrawingUpdate, user: User) -> ChartDrawing:
        self._ensure_can_access(drawing, user)
        self._ensure_can_edit(drawing, user)
        data = payload.model_dump(exclude_unset=True)
        if "name" in data:
            drawing.name = data["name"].strip() if isinstance(data["name"], str) and data["name"].strip() else None
        if "payload" in data and data["payload"] is not None:
            drawing.payload_json = validate_drawing_payload(drawing.drawing_type, data["payload"])
        if "style" in data and data["style"] is not None:
            drawing.style_json = normalize_style(data["style"])
        if "metadata" in data and data["metadata"] is not None:
            if not isinstance(data["metadata"], dict):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="metadata must be an object")
            drawing.metadata_json = data["metadata"]
        if "visible" in data and data["visible"] is not None:
            drawing.visible = data["visible"]
        if "locked" in data and data["locked"] is not None:
            if user.role != UserRole.admin:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admin can lock drawings")
            drawing.locked = data["locked"]
        self.db.commit()
        self.db.refresh(drawing)
        return drawing

    def soft_delete(self, drawing: ChartDrawing, user: User) -> None:
        self._ensure_can_access(drawing, user)
        self._ensure_can_edit(drawing, user)
        drawing.visible = False
        drawing.deleted_at = datetime.now(UTC)
        self.db.commit()

    def to_read(self, drawing: ChartDrawing) -> ChartDrawingRead:
        return ChartDrawingRead(
            id=drawing.id,
            user_id=drawing.user_id,
            internal_symbol=drawing.internal_symbol,
            timeframe=drawing.timeframe,  # type: ignore[arg-type]
            drawing_type=drawing.drawing_type,
            name=drawing.name,
            payload=drawing.payload_json,
            style=drawing.style_json,
            metadata=drawing.metadata_json,
            locked=drawing.locked,
            visible=drawing.visible,
            source=drawing.source,
            created_at=drawing.created_at,
            updated_at=drawing.updated_at,
        )

    def _ensure_symbol_exists(self, symbol: str) -> None:
        mapping = self.db.query(SymbolMapping).filter(SymbolMapping.internal_symbol == symbol.upper()).one_or_none()
        if mapping is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown symbol: {symbol}")

    def _ensure_can_mutate(self, user: User) -> None:
        if user.role not in {UserRole.admin, UserRole.trader}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User role cannot modify drawings")

    def _ensure_can_access(self, drawing: ChartDrawing, user: User) -> None:
        if user.role == UserRole.admin:
            return
        if drawing.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drawing not found")

    def _ensure_can_edit(self, drawing: ChartDrawing, user: User) -> None:
        self._ensure_can_mutate(user)
        if drawing.locked and user.role != UserRole.admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Locked drawings can only be edited by admin")
