from pathlib import Path

_SKILLS_DIR = Path(__file__).parent


def load_skill(name: str) -> str:
    p = _SKILLS_DIR / f"{name}.md"
    if not p.exists():
        raise FileNotFoundError(f"skill not found: {name}")
    return p.read_text(encoding="utf-8")


def load_skills(names: list[str]) -> str:
    """Concatenate multiple skills with a visual divider so the agent reads
    them as distinct discipline pages."""
    return "\n\n---\n\n".join(load_skill(n) for n in names)
