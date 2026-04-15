"""Seed reviewer/viewer test users for the regression tester.

Usage (production):
    docker compose exec backend python -m app.seed_test_users

Idempotent — safe to run repeatedly. Resets the password and role on each run
so the tester always has a known-good login.
"""

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.user import User

settings = get_settings()


TEST_USERS = [
    {
        "email": "test-reviewer@reventlabs.com",
        "password": "TestReview123",
        "name": "Test Reviewer",
        "role": "reviewer",
    },
    {
        "email": "test-viewer@reventlabs.com",
        "password": "TestView123",
        "name": "Test Viewer",
        "role": "viewer",
    },
]


def hash_password(password: str) -> str:
    salted = f"{settings.jwt_secret}:{password}"
    return hashlib.sha256(salted.encode()).hexdigest()


async def seed():
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        for u in TEST_USERS:
            result = await session.execute(select(User).where(User.email == u["email"]))
            existing = result.scalar_one_or_none()

            if existing:
                existing.password_hash = hash_password(u["password"])
                existing.role = u["role"]
                existing.is_active = True
                print(f"Updated existing user: {u['email']} ({u['role']})")
            else:
                user = User(
                    id=uuid.uuid4(),
                    email=u["email"],
                    name=u["name"],
                    role=u["role"],
                    password_hash=hash_password(u["password"]),
                    is_active=True,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(user)
                print(f"Created user: {u['email']} ({u['role']})")

        await session.commit()

    await engine.dispose()

    print("\nTest credentials ready:")
    for u in TEST_USERS:
        print(f"  {u['role']:8s}  {u['email']:32s}  password: {u['password']}")
    print()


if __name__ == "__main__":
    asyncio.run(seed())
