"""User / Team pydantic models for the multi-tenancy layer (2026-06-03).

Mirrors label-studio's concepts on a filesystem store (no DB, per emerge's
spine): Organization→Team, Organization.token→Team.invite_token,
User.active_organization→User.active_team_id. Stored as JSON rows under
`_auth/{users,teams}.json` at the TRUE workspace root.

`extra='forbid'` keeps the on-disk shape honest — a typo'd field name fails
loud at load instead of silently dropping. `password_hash` is stored but MUST
never be serialised into an API response (see `User.public()`).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    email: str  # always stored lowercased; the login/lookup key
    password_hash: str  # pbkdf2$... — never leaves the backend
    full_name: str = ""
    display_name: str = ""
    team_ids: list[str] = Field(default_factory=list)
    active_team_id: str | None = None
    is_superuser: bool = False
    created_at: str

    def public(self) -> dict:
        """Safe-to-serialise projection — drops `password_hash`. Every route
        that returns a user MUST go through this (no raw `model_dump`)."""
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "display_name": self.display_name,
            "team_ids": list(self.team_ids),
            "active_team_id": self.active_team_id,
            "is_superuser": self.is_superuser,
            "created_at": self.created_at,
        }


class Team(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    invite_token: str  # the shareable `/signup?token=` secret
    created_by: str  # user id — audit only, NOT an owner/admin privilege
    member_ids: list[str] = Field(default_factory=list)
    created_at: str

    def public(self) -> dict:
        """Team projection for member-facing responses. `invite_token` IS
        included — any member may reshare the link (no admin tier)."""
        return {
            "id": self.id,
            "name": self.name,
            "invite_token": self.invite_token,
            "created_by": self.created_by,
            "member_ids": list(self.member_ids),
            "created_at": self.created_at,
        }
