from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from app.exports.readme_template import render_readme
from app.workspace.paths import project_json_path, schema_path, version_path


_PLACEHOLDER_KEY = "<your saved key>"
_PLACEHOLDER_PUB = "<your published_id>"


class BundleVersionMissingError(Exception):
    """Raised when the requested frozen version is absent."""


def _curl_script(published_id: str | None) -> str:
    pub = published_id or _PLACEHOLDER_PUB
    return f"""#!/usr/bin/env sh
HOST="${{HOST:-https://example.com}}"
PUB="{pub}"
KEY="{_PLACEHOLDER_KEY}"
PDF_PATH="${{1:-/path/to/document.pdf}}"

curl -X POST "${{HOST}}/v1/extract" \\
  -H "X-API-Key: ${{KEY}}" \\
  -F "published_id=${{PUB}}" \\
  -F "file=@${{PDF_PATH}}"
"""


def build_zip_bundle(
    *,
    workspace: Path,
    slug: str,
    version_n: int,
    published_id: str | None = None,
) -> bytes:
    """Build the export ZIP for one frozen version.

    `slug` is the folder handle (post slug-transparency); the curl example
    embeds `published_id` (the public API parameter), not the slug — public
    extraction calls `POST /v1/extract` + `published_id=pub_xxx`.
    """
    vp = version_path(workspace, slug, version_n)
    if not vp.exists():
        raise BundleVersionMissingError(f"versions/v{version_n}.json missing")

    version_blob: dict[str, Any] = json.loads(vp.read_text(encoding="utf-8"))
    pj = project_json_path(workspace, slug)
    project_blob: dict[str, Any] = json.loads(pj.read_text(encoding="utf-8")) if pj.exists() else {}
    sp = schema_path(workspace, slug)
    schema_blob: list[Any] = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else []

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("schema.json", json.dumps(schema_blob, indent=2, ensure_ascii=False))
        z.writestr("version.json", json.dumps(version_blob, indent=2, ensure_ascii=False))
        z.writestr("curl_example.sh", _curl_script(published_id))
        z.writestr(
            "README.md",
            render_readme(
                project=project_blob,
                version=version_blob,
                slug=slug,
                published_id=published_id,
            ),
        )
    return buf.getvalue()
