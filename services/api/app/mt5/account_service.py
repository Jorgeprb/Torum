from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.mt5.models import SavedMT5Account
from app.mt5.schemas import MT5AccountPayload, SavedMT5AccountCreate, SavedMT5AccountRead
from app.users.models import User


class SavedMT5AccountService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_user(self, user: User, active: MT5AccountPayload | None = None) -> list[SavedMT5AccountRead]:
        rows = list(
            self.db.scalars(
                select(SavedMT5Account)
                .where(SavedMT5Account.user_id == user.id)
                .order_by(SavedMT5Account.alias, SavedMT5Account.id)
            )
        )
        return [self.to_read(row, active) for row in rows]

    def get_for_user(self, user: User, account_id: int) -> SavedMT5Account:
        row = self.db.get(SavedMT5Account, account_id)
        if row is None or row.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MT5 account not found")
        return row

    def create(self, user: User, payload: SavedMT5AccountCreate, active: MT5AccountPayload | None = None) -> SavedMT5Account:
        server = payload.server.strip()
        alias = (payload.alias or "").strip() or f"{payload.login} · {server}"
        row = SavedMT5Account(user_id=user.id, alias=alias, login=payload.login, server=server)
        if _same_account_values(payload.login, server, active):
            self._copy_last_known(row, active)
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This MT5 account is already saved") from exc
        self.db.refresh(row)
        return row

    def rename(self, user: User, account_id: int, alias: str) -> SavedMT5Account:
        row = self.get_for_user(user, account_id)
        row.alias = alias.strip()
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, user: User, account_id: int) -> None:
        row = self.get_for_user(user, account_id)
        self.db.delete(row)
        self.db.commit()

    def mark_connected(self, row: SavedMT5Account, account: MT5AccountPayload) -> None:
        self._copy_last_known(row, account)
        self.db.commit()
        self.db.refresh(row)

    def to_read(self, row: SavedMT5Account, active: MT5AccountPayload | None = None) -> SavedMT5AccountRead:
        return SavedMT5AccountRead(
            id=row.id,
            alias=row.alias,
            login=row.login,
            server=row.server,
            last_trade_mode=row.last_trade_mode if row.last_trade_mode in {"DEMO", "REAL", "UNKNOWN"} else None,
            last_company=row.last_company,
            last_currency=row.last_currency,
            last_connected_at=row.last_connected_at,
            active=_same_account_values(row.login, row.server, active),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _copy_last_known(row: SavedMT5Account, account: MT5AccountPayload | None) -> None:
        if account is None:
            return
        row.last_trade_mode = account.trade_mode
        row.last_company = account.company
        row.last_currency = account.currency
        row.last_connected_at = datetime.now(UTC)


def _same_account_values(login: int | None, server: str | None, active: MT5AccountPayload | None) -> bool:
    if active is None or active.login is None:
        return False
    return int(login or 0) == int(active.login) and (server or "").strip().casefold() == (active.server or "").strip().casefold()
