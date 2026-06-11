"""Python projection of the audit-board geometry single source of truth.

``app/skills/board_geometry.js`` owns EVERY shared geometry constant (plan
docs/superpowers/plans/2026-06-12-board-geometry-and-doodle-signal.md, §G —
born after the same formula was hand-ported three times and drifted). This
module is consumer #3 of that file: it regex-extracts the strict-JSON literal
between the ``/*GEOM-JSON-BEGIN*/`` / ``/*GEOM-JSON-END*/`` markers and
``json.loads`` it — zero JS runtime.

Hard rule: NEVER define a geometry constant in Python. Anything pad/stroke/
dash/scale-shaped must be derived from :func:`load_geom` so the web board,
the MCP iframe board and the Pillow composite can never drift apart again
(``tests/unit/test_board_geom.py`` gates this).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

# Same locator convention as mcp_server.py::_board_app_html — the skills dir
# sits beside this package: app/tools/ → app/skills/.
_GEOMETRY_JS = Path(__file__).resolve().parent.parent / "skills" / "board_geometry.js"

_MARKER_RE = re.compile(
    r"/\*GEOM-JSON-BEGIN\*/(?P<json>.*?)/\*GEOM-JSON-END\*/", re.DOTALL
)


@lru_cache(maxsize=1)
def load_geom() -> dict:
    """The GEOM constants from board_geometry.js, parsed once per process.

    Fails LOUD (ValueError / json.JSONDecodeError / OSError) on a missing
    file, missing markers or non-strict JSON between them — silent fallback
    numbers are exactly the drift this module exists to kill."""
    text = _GEOMETRY_JS.read_text(encoding="utf-8")
    m = _MARKER_RE.search(text)
    if m is None:
        raise ValueError(
            f"GEOM-JSON markers not found in {_GEOMETRY_JS} — "
            "board_geometry.js must keep the /*GEOM-JSON-BEGIN*/ literal"
        )
    return json.loads(m.group("json"))
