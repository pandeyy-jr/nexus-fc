import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-that-is-at-least-32-chars")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.roles import RoleName
from app.db.base import Base
from app.db.database import get_engine, get_session
from app.db.models.role import Role
from app.main import app


@dataclass(frozen=True)
class DatabaseFixture:
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture
async def database() -> AsyncIterator[DatabaseFixture]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as session:
        session.add_all(
            [
                Role(name=role, description=role.value.replace("_", " ").title())
                for role in RoleName
            ]
        )
        await session.commit()

    yield DatabaseFixture(engine=engine, sessions=sessions)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(database: DatabaseFixture) -> AsyncIterator[AsyncClient]:
    async def override_session() -> AsyncIterator[AsyncSession]:
        async with database.sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_engine] = lambda: database.engine

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
