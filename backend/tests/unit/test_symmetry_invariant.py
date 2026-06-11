"""Tool ↔ HTTP dual-form invariant (M11 T14 closeout).

The AI-native API symmetry principle (memory `feedback_ai_native_api_symmetry`)
says every lab action must be reachable from a CLI client driving HTTP, not
just from the in-session agent driving its tool surface. M11 Phase B added the
13 missing HTTP routes; this test locks in the contract going forward.

The test does two things:

1. **Every ``@tool(...)`` registration must be either**
   - mapped to a live HTTP route via ``_TOOL_HTTP_MAP``, or
   - in ``_HTTP_EXEMPT`` with a one-line justification.

   Adding a new tool without thinking about its HTTP form trips this test —
   either add a route or add the tool name to the exempt set with a comment
   explaining *why* it is tool-only.

2. **Every entry in ``_TOOL_HTTP_MAP`` must match a live FastAPI route.**
   Catches drift the other direction — if someone deletes / renames an HTTP
   route, the symmetry map breaks and the test fails loudly.

See ``docs/superpowers/INSIGHTS.md`` §15 for the enforcement rationale and
``docs/superpowers/plans/2026-05-19-turn-as-resource.md`` §Phase B for the
audit that produced the Phase B route fillers.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.routing import APIRoute

import app.tools as _tools_pkg
from app.main import app


# ---------------------------------------------------------------------------
# Exempt set — tools that intentionally have no HTTP counterpart.
# Each entry MUST be accompanied by a one-line comment naming the reason.
# ---------------------------------------------------------------------------

_HTTP_EXEMPT: dict[str, str] = {
    # UI side-channel — these only steer the in-session browser view and have
    # no meaning for a CLI client driving HTTP. The agent emits them; the
    # frontend listens on the SSE bus. A headless caller silently ignores
    # them and the agent's reply still lands.
    "ui_goto_page":         "ui side-channel; agent→UI only, CLI clients ignore",
    "ui_set_active_field":  "ui side-channel; agent→UI only, CLI clients ignore",
    "ui_set_active_tab":    "ui side-channel; agent→UI only, CLI clients ignore",
    "ui_set_active_entity": "ui side-channel; agent→UI only, CLI clients ignore",
    # `get_surface_state` reads the frontend's current review-mode pointer; a
    # CLI caller already knows what doc it asked about (it passed the slug
    # and filename in), so there is no symmetric HTTP form to expose.
    "get_surface_state":    "introspects in-session UI surface; CLI knows its own pointer",
    # `ask_user` is an agent→client *request* that blocks on a chat-scoped
    # asyncio future. Its HTTP counterpart is the *resolution* side —
    # `POST /lab/chats/{chat_id}/ask_user/{request_id}` — not a symmetric
    # "issue an ask_user" route. CLI clients drive their own prompts; they
    # never need to invoke ask_user from the outside.
    "ask_user":             "ask_user is the request half; resolution via POST /lab/chats/{cid}/ask_user/{rid}",
}


# ---------------------------------------------------------------------------
# Canonical tool → HTTP route mapping. The pattern is a fragment matched with
# ``re.search`` against ``APIRoute.path`` (so we don't have to copy FastAPI's
# ``{name:converter}`` syntax char-for-char). Use the most specific pattern
# that uniquely identifies the route.
# ---------------------------------------------------------------------------

_TOOL_HTTP_MAP: dict[str, tuple[str, str]] = {
    # Project lifecycle
    "create_project":             ("POST",   r"^/lab/projects$"),
    "delete_project":             ("DELETE", r"^/lab/projects/\{slug\}$"),
    "fork_project":               ("POST",   r"^/lab/projects/fork$"),
    "promote_chat_to_project":    ("POST",   r"^/lab/chats/\{chat_id\}/promote$"),
    "promote_attachment_to_docs": ("POST",   r"^/lab/projects/\{slug\}/chats/\{chat_id\}/attachments/\{filename:path\}/promote$"),
    # Pro labeler
    "label_docs":         ("POST", r"^/lab/projects/\{slug\}/label_docs$"),
    "set_labeler_model":  ("POST", r"^/lab/projects/\{slug\}/labeler_model$"),
    "get_labeler_config": ("GET",  r"^/lab/projects/\{slug\}/labeler_config$"),
    # Project LLM-role config (/config surface)
    "get_project_config": ("GET",  r"^/lab/projects/\{slug\}/config$"),
    "set_translate_model": ("PUT", r"^/lab/projects/\{slug\}/translate_model$"),
    "set_proposer_model":  ("PUT", r"^/lab/projects/\{slug\}/proposer_model$"),
    # Doc vision — both tools surface through the shared docs by-name page
    # render route (PDF→PNG / image bytes). The route doesn't take a
    # ``page`` body arg by name (it's part of the URL), but the byte-on-the-
    # wire output is what `read_doc_image` ships inline as base64.
    "pdf_render_page": ("GET", r"^/lab/projects/\{slug\}/docs/by-name/\{filename:path\}/pages/\{page\}$"),
    "read_doc_image":  ("GET", r"^/lab/projects/\{slug\}/docs/by-name/\{filename:path\}/pages/\{page\}$"),
    "extract_textlayer": ("GET", r"^/lab/projects/\{slug\}/docs/by-name/\{filename:path\}/textlayer$"),
    "translate_page":    ("POST", r"^/lab/projects/\{slug\}/docs/by-name/\{filename:path\}/translate$"),
    # Schema axes
    "derive_schema":      ("POST", r"^/lab/projects/\{slug\}/schema/derive$"),
    "write_schema":       ("POST", r"^/lab/projects/\{slug\}/schema$"),
    "import_schema_from_yaml": ("POST", r"^/lab/projects/\{slug\}/chats/\{chat_id\}/attachments/\{filename:path\}/import-schema$"),
    "add_model":            ("POST", r"^/lab/projects/\{slug\}/models$"),
    "switch_active_model":  ("PUT",  r"^/lab/projects/\{slug\}/models/active$"),
    "switch_active_prompt": ("POST", r"^/lab/projects/\{slug\}/prompts/\{prompt_id\}/activate$"),
    # Experiments
    "create_experiment":       ("POST", r"^/lab/projects/\{slug\}/experiments$"),
    "extract_with_experiment": ("POST", r"^/lab/projects/\{slug\}/experiments/\{experiment_id\}/predictions/\{filename:path\}$"),
    "run_experiment_eval":     ("POST", r"^/lab/projects/\{slug\}/experiments/\{experiment_id\}/eval$"),
    "promote_experiment":      ("POST", r"^/lab/projects/\{slug\}/experiments/\{experiment_id\}/promote$"),
    # Extract + score + readiness + contract-diff
    "extract_one":     ("POST", r"^/lab/projects/\{slug\}/extract$"),
    "save_reviewed":   ("POST", r"^/lab/projects/\{slug\}/reviewed/\{filename:path\}$"),
    "score":           ("POST", r"^/lab/projects/\{slug\}/score$"),
    "readiness_check": ("GET",  r"^/lab/projects/\{slug\}/readiness$"),
    "contract_diff":   ("GET",  r"^/lab/projects/\{slug\}/contract-diff$"),
    # Bench leaderboard (project-level horizontal view of prompt × model evals).
    # Both forms thin-delegate to `app.services.bench.compute_bench`.
    "bench_view":      ("GET",  r"^/lab/projects/\{slug\}/bench$"),
    # Document matching (reconciliation) — app/api/routes/match.py.
    "create_match_project": ("POST", r"^/lab/match/projects$"),
    "write_match_prompt":   ("PUT",  r"^/lab/match/projects/\{slug\}/prompt$"),
    "run_match":            ("POST", r"^/lab/match/projects/\{slug\}/run$"),
    "save_reviewed_match":  ("POST", r"^/lab/match/projects/\{slug\}/reviewed$"),
    "score_match":          ("GET",  r"^/lab/match/projects/\{slug\}/score$"),
    "write_audit_rules":    ("PUT",  r"^/lab/projects/\{slug\}/audit-rules$"),
    "run_audit":            ("POST", r"^/lab/projects/\{slug\}/audit$"),
    "read_audit_report":    ("GET",  r"^/lab/projects/\{slug\}/audit/latest$"),
    # B4 board render — annotated evidence images (pixels + rule text only;
    # the board-notes GET/PUT siblings are render-layer persistence and stay
    # route-without-tool, same as locate / locate-quotes).
    "render_audit_board":   ("GET",  r"^/lab/projects/\{slug\}/audit/board-render$"),
    "save_reviewed_audit":  ("PUT",  r"^/lab/projects/\{slug\}/audit-review$"),
    "score_audit":          ("POST", r"^/lab/projects/\{slug\}/audit-score$"),
    # Publish + keys
    "freeze_version": ("POST", r"^/lab/projects/\{slug\}/versions/freeze$"),
    "issue_api_key":  ("POST", r"^/lab/keys$"),
    # Jobs
    "start_job":  ("POST", r"^/lab/jobs$"),
    "get_job":    ("GET",  r"^/lab/jobs/\{job_id\}$"),
    "pause_job":  ("POST", r"^/lab/jobs/\{job_id\}/pause$"),
    "resume_job": ("POST", r"^/lab/jobs/\{job_id\}/resume$"),
    "cancel_job": ("POST", r"^/lab/jobs/\{job_id\}/cancel$"),
    # Version history (per-team git timeline)
    "history_log":     ("GET",  r"^/lab/history$"),
    "history_diff":    ("GET",  r"^/lab/history/diff$"),
    "history_restore": ("POST", r"^/lab/history/restore$"),
    # Headless discovery tools — registered only on the stdio/remote MCP
    # surface (build_emerge_mcp(headless=True)); the in-session chat agent
    # discovers via built-in Bash/Read instead. Their HTTP twins predate the
    # Step B wrapper cut and are still live, so the dual-form contract holds.
    "list_projects": ("GET", r"^/lab/projects$"),
    "list_docs":     ("GET", r"^/lab/projects/\{slug\}/docs$"),
    # read_prompt returns the active prompt (schema + global_notes) — its twin is
    # the active-prompt route, NOT schema/raw (which is fields-only YAML).
    "read_prompt":   ("GET", r"^/lab/projects/\{slug\}/prompts/active$"),
    # Workspace filesystem bus (headless): generic ws_* tools share their pure
    # logic with these team-scoped twins (app/api/routes/ws.py).
    "ws_list":       ("GET", r"^/lab/ws/list$"),
    "ws_read":       ("GET", r"^/lab/ws/read$"),
    "ws_grep":       ("GET", r"^/lab/ws/grep$"),
    "ws_write":      ("POST", r"^/lab/ws/write$"),
    "ws_edit":       ("POST", r"^/lab/ws/edit$"),
    "ws_move":       ("POST", r"^/lab/ws/move$"),
    # Binary data plane: the tool mints capability URLs; its twin is the authed
    # mint route. The unauthed redemption endpoint (/lab/upload/{token}) is the
    # data plane itself, not a tool twin.
    "request_upload_url": ("POST", r"^/lab/upload-urls$"),
    # Progressive disclosure: domain playbooks pulled on demand.
    "read_skill":    ("GET", r"^/lab/skills/\{domain\}$"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _discover_tools() -> set[str]:
    """Parse the ``@tool("name", ...)`` registrations out of
    ``app/tools/__init__.py``. Using the source text (not importing) keeps
    this test cheap and avoids spinning up the full SDK MCP server during the
    unit suite — and catches dead-but-decorated tools the same way it catches
    live ones, which is the contract we want.

    Resolves the source path via the imported ``app.tools`` package's
    ``__file__`` so the assertion holds regardless of the test's cwd (the
    project conftest ``chdir``'s into a per-test workspace; a relative path
    would miss)."""
    tools_init = Path(_tools_pkg.__file__).resolve()
    src = tools_init.read_text(encoding="utf-8")
    # First positional argument of `@tool(...)` is the quoted tool name.
    return set(re.findall(r'@tool\(\s*"([a-z_][a-z0-9_]*)"', src))


def _route_signatures() -> set[tuple[str, str]]:
    sigs: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in (route.methods or set()):
            sigs.add((method, route.path))
    return sigs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_every_tool_has_http_or_is_exempt() -> None:
    """Every ``@tool`` registration must be mapped to an HTTP route or be in
    ``_HTTP_EXEMPT`` with a justification comment. Adding a new tool without
    thinking about its HTTP twin is the trap this guards against."""
    discovered = _discover_tools()
    mapped = set(_TOOL_HTTP_MAP)
    exempt = set(_HTTP_EXEMPT)

    unmapped = discovered - mapped - exempt
    assert not unmapped, (
        "Tools without an HTTP route and not in _HTTP_EXEMPT: "
        f"{sorted(unmapped)}. Either add the route (preferred — see Phase B "
        "of docs/superpowers/plans/2026-05-19-turn-as-resource.md for the "
        "thin-delegate pattern) or add the tool to _HTTP_EXEMPT with a "
        "one-line justification."
    )

    stale_mapped = mapped - discovered
    assert not stale_mapped, (
        f"Stale entries in _TOOL_HTTP_MAP (tool no longer registered): "
        f"{sorted(stale_mapped)}. Remove the entry."
    )
    stale_exempt = exempt - discovered
    assert not stale_exempt, (
        f"Stale entries in _HTTP_EXEMPT (tool no longer registered): "
        f"{sorted(stale_exempt)}. Remove the entry."
    )


def test_mapped_routes_actually_exist() -> None:
    """Every mapped HTTP route must be live on the FastAPI app. Catches the
    reverse drift — someone deletes / renames an HTTP route while the tool
    still ships."""
    sigs = _route_signatures()
    missing: list[str] = []
    for tool_name, (expected_method, expected_pattern) in _TOOL_HTTP_MAP.items():
        pat = re.compile(expected_pattern)
        match = any(
            method == expected_method and pat.search(path)
            for method, path in sigs
        )
        if not match:
            missing.append(f"{tool_name}: expected {expected_method} {expected_pattern}")
    assert not missing, (
        "Tools declared in _TOOL_HTTP_MAP have no matching live route:\n  "
        + "\n  ".join(missing)
    )


def test_exempt_entries_carry_justification() -> None:
    """Each _HTTP_EXEMPT entry must have a non-empty justification string so a
    future reader knows *why* the asymmetry is intentional."""
    blank = [k for k, v in _HTTP_EXEMPT.items() if not v.strip()]
    assert not blank, (
        f"_HTTP_EXEMPT entries missing justification: {blank}. Add a one-line "
        "comment-style reason explaining why this tool has no HTTP twin."
    )
