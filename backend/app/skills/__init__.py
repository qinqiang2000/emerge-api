from pathlib import Path

_SKILLS_DIR = Path(__file__).parent

# Progressive disclosure (2026-06-10): the always-on extractor skill is a slim
# core (identity / red lines / routing); per-domain playbooks live here and are
# pulled on demand via the `read_skill` tool. Explicit allowlist — the tool
# argument never touches the filesystem as a path.
SKILL_DOMAINS: tuple[str, ...] = (
    "experiments", "match_audit", "review", "attachments", "self",
)


def load_skill(name: str) -> str:
    p = _SKILLS_DIR / f"{name}.md"
    if not p.exists():
        raise FileNotFoundError(f"skill not found: {name}")
    return p.read_text(encoding="utf-8")


def load_domain_skill(domain: str) -> str:
    """Read one domain playbook. Raises KeyError on anything not in the
    allowlist (server-side guard; never path-join the raw argument)."""
    if domain not in SKILL_DOMAINS:
        raise KeyError(domain)
    return (_SKILLS_DIR / "domains" / f"{domain}.md").read_text(encoding="utf-8")


def load_skills(names: list[str]) -> str:
    """Concatenate multiple skills with a visual divider so the agent reads
    them as distinct discipline pages."""
    return "\n\n---\n\n".join(load_skill(n) for n in names)
