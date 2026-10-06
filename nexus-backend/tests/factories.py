from uuid import UUID

from sqlalchemy import select

from app.core.roles import RoleName
from app.core.security import create_access_token, hash_password
from app.db.models.role import Role
from app.db.models.user import User
from tests.conftest import DatabaseFixture


async def create_user(
    database: DatabaseFixture,
    email: str,
    role_name: RoleName = RoleName.PLAYER,
    is_active: bool = True,
) -> tuple[UUID, str]:
    async with database.sessions() as session:
        role = await session.scalar(select(Role).where(Role.name == role_name))
        assert role is not None
        user = User(
            email=email,
            full_name="Test User",
            hashed_password=hash_password("secure-password-123"),
            role=role,
            is_active=is_active,
        )
        session.add(user)
        await session.commit()
        user_id = user.id
    return user_id, create_access_token(user_id)
