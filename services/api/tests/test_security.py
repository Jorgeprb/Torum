from app.auth.security import get_password_hash, verify_password
from app.users.models import UserRole


def test_password_hash_roundtrip() -> None:
    password = "phase-1-test-password"
    hashed_password = get_password_hash(password)

    assert hashed_password != password
    assert verify_password(password, hashed_password)
    assert not verify_password("wrong-password", hashed_password)


def test_supported_roles_are_admin_and_trader_only() -> None:
    assert {role.value for role in UserRole} == {"admin", "trader"}
