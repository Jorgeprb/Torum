from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.news.repository import get_news_event
from app.news.schemas import (
    NewsCsvImportRequest,
    NewsEventCreate,
    NewsEventRead,
    NewsEventUpdate,
    NewsImportResponse,
    NewsJsonImportRequest,
    NewsProviderStatusRead,
    NewsProviderSyncResponse,
    NewsSettingsRead,
    NewsSettingsUpdate,
)
from app.news.service import NewsService, get_global_news_settings
from app.users.models import User

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/settings", response_model=NewsSettingsRead)
def read_news_settings(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> NewsSettingsRead:
    return NewsSettingsRead.model_validate(get_global_news_settings(db))


@router.patch("/settings", response_model=NewsSettingsRead)
def patch_news_settings(
    payload: NewsSettingsUpdate,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> NewsSettingsRead:
    try:
        settings, _regenerated = NewsService(db).update_settings(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return NewsSettingsRead.model_validate(settings)


@router.get("/events", response_model=list[NewsEventRead])
def list_events(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    currency: str | None = None,
    impact: str | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[NewsEventRead]:
    return [
        NewsEventRead.model_validate(event)
        for event in NewsService(db).list_events(
            start_time=from_time,
            end_time=to_time,
            currency=currency,
            impact=impact,
            limit=limit,
        )
    ]


@router.post("/events", response_model=NewsEventRead, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: NewsEventCreate,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> NewsEventRead:
    event, _zones = NewsService(db).create_event(payload)
    return NewsEventRead.model_validate(event)


@router.patch("/events/{event_id}", response_model=NewsEventRead)
def update_event(
    event_id: int,
    payload: NewsEventUpdate,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> NewsEventRead:
    event = get_news_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News event not found")
    updated, _zones = NewsService(db).update_event(event, payload)
    return NewsEventRead.model_validate(updated)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    event = get_news_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News event not found")
    NewsService(db).delete_event(event)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/import/json", response_model=NewsImportResponse, status_code=status.HTTP_201_CREATED)
def import_json(
    payload: NewsJsonImportRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> NewsImportResponse:
    return NewsService(db).import_json(payload)


@router.post("/import/csv", response_model=NewsImportResponse, status_code=status.HTTP_201_CREATED)
def import_csv(
    payload: NewsCsvImportRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> NewsImportResponse:
    return NewsService(db).import_csv(payload)


@router.post("/providers/sync", response_model=NewsProviderSyncResponse)
def sync_provider(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> NewsProviderSyncResponse:
    return NewsService(db).sync_provider()


@router.get("/providers/status", response_model=NewsProviderStatusRead)
def provider_status(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> NewsProviderStatusRead:
    return NewsService(db).provider_status()
