"""board_geom (G3) — GEOM single-source parsing + drift gate.

board_geometry.js is the only place audit-board geometry numbers may live
(plan 2026-06-12 §G). These tests gate the Python side: the marker literal
stays strict JSON with every required key, load_geom() caches, and
audit_board_render.py never grows hand-copied pad/stroke literals again
(the pre-G3 hand copies had drifted 2.4× from the web board).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.tools.board_geom import _GEOMETRY_JS, _MARKER_RE, load_geom

# Keys every consumer relies on — a renamed/dropped key must fail HERE, not
# as a KeyError deep inside a renderer.
_REQUIRED_KEYS = {
    "SCALE", "COL_GAP", "ROW_GAP", "PAGES_PER_COL", "ELLIPSE_PAD",
    "ARROW_GAP", "STROKE_W", "STROKE_ARROW", "DASH_ON", "DASH_OFF",
    "RENDER_DPI",
}

_RENDER_PY = (
    Path(__file__).resolve().parents[2] / "app" / "tools" / "audit_board_render.py"
)


def test_load_geom_parses_with_all_required_keys():
    geom = load_geom()
    assert _REQUIRED_KEYS <= set(geom)


def test_geom_values_are_sane_numbers():
    geom = load_geom()
    # SCALE is the board-unit ↔ source-pixel ratio — a fraction, never 0/≥1.
    assert isinstance(geom["SCALE"], float) and 0 < geom["SCALE"] < 1
    for key in _REQUIRED_KEYS - {"SCALE"}:
        assert isinstance(geom[key], (int, float)), key
        assert geom[key] > 0, key
    assert isinstance(geom["PAGES_PER_COL"], int)
    assert isinstance(geom["RENDER_DPI"], int)


def test_load_geom_is_cached():
    assert load_geom() is load_geom()  # lru_cache returns the same object


def test_marker_literal_is_strict_json():
    """The marker section must json.loads as-is — consumer #3 has no JS
    runtime, so comments / single quotes / trailing commas inside it break
    the Pillow path. load_geom() raising is the failure; reaching here with
    a real marker match is the proof."""
    text = _GEOMETRY_JS.read_text(encoding="utf-8")
    assert _MARKER_RE.search(text) is not None
    load_geom()  # would raise json.JSONDecodeError on non-strict JSON


def test_render_constants_derive_from_geom_not_hand_copies():
    """Drift gate: _RECT_PAD/_OUTLINE_W definitions in audit_board_render.py
    must reference GEOM (load_geom-backed), never a bare literal like the
    pre-G3 `= 6` / `= 5` hand copies that drifted from the web board."""
    src = _RENDER_PY.read_text(encoding="utf-8")
    for name in ("_RECT_PAD", "_OUTLINE_W", "_GAP_DEG"):
        defs = re.findall(rf"^{name}\s*=\s*(.+)$", src, re.MULTILINE)
        assert len(defs) == 1, f"{name} must have exactly one definition"
        assert re.search(r"load_geom\(\)|_GEOM\[", defs[0]), (
            f"{name} must derive from GEOM, got: {name} = {defs[0]}"
        )
        assert not re.fullmatch(r"\d+(\.\d+)?\s*(#.*)?", defs[0]), (
            f"{name} is a hand-written literal again: {defs[0]}"
        )


def test_derived_render_constants_match_board_semantics():
    """Source-pixel semantics: board pad/stroke are board units = source px ×
    SCALE, so the renderer's source-px values are board / SCALE; the PIL dash
    rhythm keeps its degree dialect but the on:off ratio follows DASH_ON:OFF.
    Asserted via the same derivation (not literals) so retuning the JS file
    never breaks this test — only a broken derivation does."""
    from app.tools import audit_board_render as r

    geom = load_geom()
    assert r._RECT_PAD == round(geom["ELLIPSE_PAD"] / geom["SCALE"])
    assert r._OUTLINE_W == round(geom["STROKE_W"] / geom["SCALE"])
    assert r._GAP_DEG == round(r._DASH_DEG * geom["DASH_OFF"] / geom["DASH_ON"])
    assert r._PDF_RECT_SCALE == geom["RENDER_DPI"] / 72.0


def test_missing_markers_fail_loud(tmp_path, monkeypatch):
    """A board_geometry.js without the marker pair must raise, not fall back
    to silent defaults (silent fallback = the drift this module kills)."""
    from app.tools import board_geom

    bad = tmp_path / "board_geometry.js"
    bad.write_text("const GEOM = {\"SCALE\": 0.55};\n", encoding="utf-8")
    monkeypatch.setattr(board_geom, "_GEOMETRY_JS", bad)
    load_geom.cache_clear()
    try:
        with pytest.raises(ValueError, match="GEOM-JSON markers"):
            load_geom()
    finally:
        load_geom.cache_clear()  # don't leak the patched path's cache entry
