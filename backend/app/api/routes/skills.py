"""Domain-playbook HTTP twin of the `read_skill` tool (symmetry invariant).
Progressive disclosure: the always-on extractor skill is a slim core; per-
domain playbooks are pulled on demand. See app/skills/__init__.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth.deps import bind_workspace
from app.skills import SKILL_DOMAINS, load_domain_skill

router = APIRouter(dependencies=[Depends(bind_workspace)])


@router.get("/lab/skills/{domain}")
async def get_skill_domain(domain: str) -> dict:
    try:
        return {"domain": domain, "content": load_domain_skill(domain)}
    except KeyError:
        raise HTTPException(status_code=404, detail={
            "error_code": "unknown_skill_domain",
            "error_message_en": f"no such domain: {domain!r} (have: {', '.join(SKILL_DOMAINS)})",
        })
