from __future__ import annotations

from contextvars import ContextVar, Token
from uuid import uuid4

_request_id: ContextVar[str] = ContextVar("torum_request_id", default="")


def new_request_id(candidate: str | None = None) -> str:
    value = (candidate or "").strip()
    return value[:128] if value else uuid4().hex


def set_request_id(value: str) -> Token[str]:
    return _request_id.set(value)


def reset_request_id(token: Token[str]) -> None:
    _request_id.reset(token)


def get_request_id() -> str:
    return _request_id.get()
