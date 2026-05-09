import pytest

from app.skills import load_skill, load_skills


def test_load_skill_extractor() -> None:
    text = load_skill("emerge_extractor")
    assert "emerge-extractor" in text


def test_load_skill_autoresearch_exists() -> None:
    text = load_skill("emerge_autoresearch")
    assert "autoresearch" in text.lower()
    # Discipline red lines must be encoded
    assert "schema.json" in text
    assert "candidate" in text.lower()


def test_load_skills_concatenates_with_separator() -> None:
    text = load_skills(["emerge_extractor", "emerge_autoresearch"])
    assert "emerge-extractor" in text
    assert "autoresearch" in text.lower()
    # A clear visual divider so the agent sees them as two skills
    assert "---" in text or "\n\n---\n\n" in text


def test_load_skill_missing_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_skill("not_a_real_skill")
