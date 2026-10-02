"""Operator commands. Usage: python -m app.cli create-platform-admin

Reads PLATFORM_ADMIN_EMAIL, PLATFORM_ADMIN_NAME and PLATFORM_ADMIN_PASSWORD from the environment
(see .env.example). The admin sets up two-step verification at first sign-in.
"""

import asyncio
import os
import sys

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import User
from app.security import hash_password


async def create_platform_admin() -> None:
    email = os.getenv("PLATFORM_ADMIN_EMAIL", "").strip().lower()
    name = os.getenv("PLATFORM_ADMIN_NAME", "").strip() or "Platform Admin"
    password = os.getenv("PLATFORM_ADMIN_PASSWORD", "")
    if not email or len(password) < 10:
        sys.exit("Set PLATFORM_ADMIN_EMAIL and PLATFORM_ADMIN_PASSWORD (10+ characters) in .env")
    async with get_sessionmaker()() as db:
        if (await db.execute(select(User.id).where(User.email == email))).first():
            sys.exit("An account with that email already exists.")
        db.add(
            User(
                name=name,
                email=email,
                password_hash=hash_password(password),
                is_platform_admin=True,
            )
        )
        await db.commit()
    print(f"Platform admin created: {email}. Password: set via PLATFORM_ADMIN_PASSWORD in .env")


def main() -> None:
    commands = {"create-platform-admin": create_platform_admin}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"Usage: python -m app.cli [{'|'.join(commands)}]")
    asyncio.run(commands[sys.argv[1]]())


if __name__ == "__main__":
    main()
