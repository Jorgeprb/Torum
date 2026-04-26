from pydantic import BaseModel

from app.users.models import UserRole


class UserRead(BaseModel):
    id: int
    username: str
    email: str
    role: UserRole
    is_active: bool

    model_config = {"from_attributes": True}
