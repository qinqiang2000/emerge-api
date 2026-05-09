from __future__ import annotations

from typing import Any


_PLACEHOLDER_KEY = "<your saved key>"


def _field_row(f: dict[str, Any]) -> str:
    name = f.get("name", "")
    typ = f.get("type", "")
    desc = (f.get("description") or "").replace("|", "\\|").replace("\n", " ")
    enum = f.get("enum") or []
    if enum:
        desc = f"{desc} _(allowed: {', '.join(enum)})_"
    required = "yes" if f.get("required") else "no"
    return f"| `{name}` | {typ} | {required} | {desc} |"


def render_readme(*, project: dict[str, Any], version: dict[str, Any], project_id: str) -> str:
    name = project.get("name", "(unnamed project)")
    version_id = version.get("version_id", "(unknown version)")
    model_id = version.get("model_id", "(unknown model)")
    fields = version.get("schema", []) or []
    notes = version.get("global_notes") or ""
    frozen_at = version.get("frozen_at", "")

    lines: list[str] = [
        f"# {name} extraction API ({version_id})",
        "",
        f"- **Project ID:** `{project_id}`",
        f"- **Active version:** `{version_id}` (frozen {frozen_at})",
        f"- **Extraction model:** `{model_id}`",
        "",
        "## Field schema",
        "",
    ]
    if fields:
        lines.extend([
            "| Name | Type | Required | Description |",
            "|---|---|---|---|",
        ])
        for f in fields:
            lines.append(_field_row(f))
    else:
        lines.append("_(empty schema - this should not happen for a published version.)_")
    lines.append("")

    if notes.strip():
        lines.extend(["## Global notes", "", notes.strip(), ""])

    lines.extend([
        "## Calling the API",
        "",
        "```sh",
        f"curl -X POST https://<host>/v1/{project_id}/extract \\",
        f'  -H "X-API-Key: {_PLACEHOLDER_KEY}" \\',
        "  -F file=@/path/to/document.pdf",
        "```",
        "",
        "## Response shape",
        "",
        "```json",
        "{",
        '  "entities": [',
        "    {",
    ])

    sample_lines: list[str] = []
    for f in fields[:3]:
        n = f.get("name")
        t = f.get("type")
        if t == "number":
            sample_lines.append(f'      "{n}": 0')
        elif t == "boolean":
            sample_lines.append(f'      "{n}": true')
        elif t == "date":
            sample_lines.append(f'      "{n}": "2026-01-01"')
        else:
            sample_lines.append(f'      "{n}": "..."')
    if sample_lines:
        lines.append(",\n".join(sample_lines))

    lines.extend([
        "    }",
        "  ],",
        '  "_evidence": [',
        '    { "field_name": 1 }',
        "  ]",
        "}",
        "```",
        "",
    ])
    return "\n".join(lines)
