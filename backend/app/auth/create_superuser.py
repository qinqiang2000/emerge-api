"""`python -m app.auth.create_superuser` — bootstrap the first superuser.

Seeds from `EMERGE_SUPERUSER_EMAIL` / `EMERGE_SUPERUSER_PASSWORD` when set,
else prompts. The password is never echoed or logged. Idempotent: re-running
when a superuser already exists prints the existing one and changes nothing.
"""

from __future__ import annotations

import asyncio
import getpass
import sys

from app.auth.bootstrap import bootstrap_superuser
from app.config import get_settings


def main() -> None:
    settings = get_settings()
    email = (settings.superuser_email or "").strip()
    if not email:
        email = input("Superuser email: ").strip()
    if "@" not in email:
        print("error: a valid email is required", file=sys.stderr)
        raise SystemExit(2)
    password = settings.superuser_password or getpass.getpass("Password: ")
    if not password:
        print("error: password must be non-empty", file=sys.stderr)
        raise SystemExit(2)

    su = asyncio.run(
        bootstrap_superuser(settings.workspace_root, email=email, password=password)
    )
    print(f"superuser ready: {su.email} · active team {su.active_team_id}")
    print("tenant mode is now ON — /lab/* requires auth; projects live under teams/")


if __name__ == "__main__":
    main()
