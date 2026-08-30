from pydantic import BaseModel

from app.users.schemas import UserRead


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    session_token: str
    token_type: str = "bearer"
    user: UserRead


class SessionBootstrapResponse(BaseModel):
    session_token: str


class SessionRefreshRequest(BaseModel):
    session_token: str


class SessionRefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SessionLogoutRequest(BaseModel):
    session_token: str
