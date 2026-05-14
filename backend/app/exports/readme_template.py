from __future__ import annotations

from typing import Any


_PLACEHOLDER_KEY = "<your saved key>"
_PLACEHOLDER_PUB = "<your published_id>"


def _field_row(f: dict[str, Any]) -> str:
    name = f.get("name", "")
    typ = f.get("type", "")
    desc = (f.get("description") or "").replace("|", "\\|").replace("\n", " ")
    enum = f.get("enum") or []
    if enum:
        desc = f"{desc} _(allowed: {', '.join(enum)})_"
    required = "yes" if f.get("required") else "no"
    return f"| `{name}` | {typ} | {required} | {desc} |"


def render_readme(
    *,
    project: dict[str, Any],
    version: dict[str, Any],
    slug: str,
    published_id: str | None = None,
) -> str:
    name = project.get("name", "(unnamed project)")
    version_id = version.get("version_id", "(unknown version)")
    model_id = version.get("model_id", "(unknown model)")
    fields = version.get("schema", []) or []
    notes = version.get("global_notes") or ""
    frozen_at = version.get("frozen_at", "")
    pub = published_id or _PLACEHOLDER_PUB

    lines: list[str] = [
        f"# {name} extraction API ({version_id})",
        "",
        f"- **Project slug:** `{slug}`",
        f"- **Published ID:** `{pub}`",
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
        "emerge is staging — the same `published_id` syncs to production",
        "and clients call a stable URL with `published_id` as a parameter.",
        "",
        "```sh",
        "curl -X POST https://<host>/v1/extract \\",
        f'  -H "X-API-Key: {_PLACEHOLDER_KEY}" \\',
        f'  -F "published_id={pub}" \\',
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
