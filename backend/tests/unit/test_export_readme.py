from app.exports.readme_template import render_readme


def _project():
    return {
        "name": "us-invoice",
        "project_type": "extraction",
        "extract_model": "gemini-2.5-flash",
        "active_version_id": "v1",
    }


def _version():
    return {
        "version_id": "v1",
        "schema": [
            {"name": "invoice_number", "type": "string", "description": "Invoice no", "required": False},
            {"name": "total_amount", "type": "number", "description": "Total amount in document currency", "required": False},
            {"name": "currency", "type": "string", "description": "ISO 4217 currency code", "enum": ["USD", "EUR"], "required": False},
        ],
        "global_notes": "All invoices are USD unless explicitly EUR.",
        "model_id": "gemini-2.5-flash",
        "params": {"temperature": 0.0},
        "frozen_at": "2026-05-09T01:23:45Z",
    }


def test_includes_project_name_and_version() -> None:
    out = render_readme(project=_project(), version=_version(), project_id="p_abc123def456")
    assert "us-invoice" in out
    assert "v1" in out


def test_includes_field_table_with_each_field() -> None:
    out = render_readme(project=_project(), version=_version(), project_id="p_abc123def456")
    for fname in ("invoice_number", "total_amount", "currency"):
        assert fname in out


def test_includes_enum_values() -> None:
    out = render_readme(project=_project(), version=_version(), project_id="p_abc123def456")
    assert "USD" in out and "EUR" in out


def test_curl_example_uses_placeholder_not_real_key() -> None:
    out = render_readme(project=_project(), version=_version(), project_id="p_abc123def456")
    assert "<your saved key>" in out
    assert "ek_" not in out


def test_includes_curl_command() -> None:
    out = render_readme(project=_project(), version=_version(), project_id="p_abc123def456")
    assert "curl" in out
    assert "/v1/p_abc123def456/extract" in out
    assert "X-API-Key" in out
    assert 'file=@' in out


def test_includes_global_notes_when_present() -> None:
    out = render_readme(project=_project(), version=_version(), project_id="p_abc123def456")
    assert "USD unless explicitly EUR" in out


def test_omits_global_notes_section_when_empty() -> None:
    v = _version()
    v["global_notes"] = ""
    out = render_readme(project=_project(), version=v, project_id="p_abc123def456")
    assert "Global notes" not in out
