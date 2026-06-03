"""T2 (token layer) — Personal Access Tokens for headless bearer auth."""

from __future__ import annotations

from pathlib import Path

from app.auth import tokens
from app.auth.tokens import PAT_PREFIX


async def test_mint_and_verify(workspace: Path) -> None:
    plaintext, pat_id = await tokens.mint_pat(workspace, "u_alice", label="cli")
    assert plaintext.startswith(PAT_PREFIX)
    assert pat_id.startswith("pat_")
    assert await tokens.verify_pat(workspace, plaintext) == "u_alice"


async def test_verify_rejects_bad_tokens(workspace: Path) -> None:
    await tokens.mint_pat(workspace, "u_alice")
    assert await tokens.verify_pat(workspace, "emrg_pat_bogus") is None
    assert await tokens.verify_pat(workspace, "no-prefix") is None
    assert await tokens.verify_pat(workspace, "") is None


async def test_two_pats_independent(workspace: Path) -> None:
    p1, _ = await tokens.mint_pat(workspace, "u_alice", label="a")
    p2, _ = await tokens.mint_pat(workspace, "u_alice", label="b")
    assert p1 != p2
    assert await tokens.verify_pat(workspace, p1) == "u_alice"
    assert await tokens.verify_pat(workspace, p2) == "u_alice"


async def test_list_pats_hides_secrets_and_scopes_to_user(workspace: Path) -> None:
    await tokens.mint_pat(workspace, "u_alice", label="cli")
    await tokens.mint_pat(workspace, "u_bob", label="other")
    rows = await tokens.list_pats(workspace, "u_alice")
    assert len(rows) == 1
    row = rows[0]
    assert row["label"] == "cli"
    assert "hash" not in row and "user_id" not in row
    assert set(row) == {"pat_id", "label", "created_at", "last_used"}


async def test_revoke_is_scoped_and_kills_token(workspace: Path) -> None:
    plaintext, pat_id = await tokens.mint_pat(workspace, "u_alice")
    # another user can't revoke it
    assert await tokens.revoke_pat(workspace, pat_id, "u_bob") is False
    assert await tokens.verify_pat(workspace, plaintext) == "u_alice"
    # owner can
    assert await tokens.revoke_pat(workspace, pat_id, "u_alice") is True
    assert await tokens.verify_pat(workspace, plaintext) is None
    # revoking again → False
    assert await tokens.revoke_pat(workspace, pat_id, "u_alice") is False


async def test_last_used_stamped_after_verify(workspace: Path) -> None:
    plaintext, _ = await tokens.mint_pat(workspace, "u_alice")
    assert (await tokens.list_pats(workspace, "u_alice"))[0]["last_used"] is None
    await tokens.verify_pat(workspace, plaintext)
    last_used = (await tokens.list_pats(workspace, "u_alice"))[0]["last_used"]
    assert last_used is not None
