import pytest

from app.core.config import Settings


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        (
            "postgresql://user:password@db.example:5432/club?sslmode=require",
            "postgresql+psycopg://user:password@db.example:5432/club?sslmode=require",
        ),
        (
            "postgres://user:password@db.example:5432/club?sslmode=require",
            "postgresql+psycopg://user:password@db.example:5432/club?sslmode=require",
        ),
        (
            "postgresql+psycopg://user:password@localhost:5432/club",
            "postgresql+psycopg://user:password@localhost:5432/club",
        ),
        (
            "sqlite+aiosqlite:///:memory:",
            "sqlite+aiosqlite:///:memory:",
        ),
    ],
)
def test_database_url_uses_psycopg_for_standard_postgresql_urls(
    database_url: str, expected: str
) -> None:
    settings = Settings(
        database_url=database_url,
        jwt_secret_key="test-secret-that-is-at-least-32-chars",
    )

    assert settings.database_url == expected
