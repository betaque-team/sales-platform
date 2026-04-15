"""Seed an admin user with email/password credentials."""

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

ADMIN_EMAIL = "admin@jobplatform.io"
ADMIN_PASSWORD = "admin123"
ADMIN_NAME = "Platform Admin"


def hash_password(password: str) -> str:
    salted = f"{settings.jwt_secret}:{password}"
    return hashlib.sha256(salted.encode()).hexdigest()


async def seed():
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(select(User).where(User.email == ADMIN_EMAIL))
        existing = result.scalar_one_or_none()

        if existing:
            existing.password_hash = hash_password(ADMIN_PASSWORD)
            existing.role = "super_admin"
            existing.is_active = True
            print(f"Updated existing admin user: {ADMIN_EMAIL}")
        else:
            user = User(
                id=uuid.uuid4(),
                email=ADMIN_EMAIL,
                name=ADMIN_NAME,
                role="super_admin",
                password_hash=hash_password(ADMIN_PASSWORD),
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
            session.add(user)
            print(f"Created admin user: {ADMIN_EMAIL}")

        await session.commit()

    await engine.dispose()
    print(f"\n  Email:    {ADMIN_EMAIL}")
    print(f"  Password: {ADMIN_PASSWORD}")
    print(f"  Role:     super_admin\n")


if __name__ == "__main__":
    asyncio.run(seed())
