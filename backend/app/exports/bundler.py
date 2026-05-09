from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from app.exports.readme_template import render_readme
from app.workspace.paths import project_json_path, schema_path, version_path


_PLACEHOLDER_KEY = "<your saved key>"


class BundleVersionMissingError(Exception):
    """Raised when the requested frozen version is absent."""


def _curl_script(project_id: str) -> str:
    return f"""#!/usr/bin/env sh
HOST="${{HOST:-https://example.com}}"
PID="{project_id}"
KEY="{_PLACEHOLDER_KEY}"
PDF_PATH="${{1:-/path/to/document.pdf}}"

curl -X POST "${{HOST}}/v1/${{PID}}/extract" \\
  -H "X-API-Key: ${{KEY}}" \\
  -F "file=@${{PDF_PATH}}"
"""


def build_zip_bundle(*, workspace: Path, project_id: str, version_n: int) -> bytes:
    vp = version_path(workspace, project_id, version_n)
    if not vp.exists():
        raise BundleVersionMissingError(f"versions/v{version_n}.json missing")

    version_blob: dict[str, Any] = json.loads(vp.read_text(encoding="utf-8"))
    pj = project_json_path(workspace, project_id)
    project_blob: dict[str, Any] = json.loads(pj.read_text(encoding="utf-8")) if pj.exists() else {}
    sp = schema_path(workspace, project_id)
    schema_blob: list[Any] = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else []

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("schema.json", json.dumps(schema_blob, indent=2, ensure_ascii=False))
        z.writestr("version.json", json.dumps(version_blob, indent=2, ensure_ascii=False))
        z.writestr("curl_example.sh", _curl_script(project_id))
        z.writestr(
            "README.md",
            render_readme(project=project_blob, version=version_blob, project_id=project_id),
        )
    return buf.getvalue()
