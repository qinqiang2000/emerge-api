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

from fastapi.routing import APIRoute

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
    "ui_open_review": "ui side-channel; agent→UI only, CLI clients ignore",
    # `ui_focus` folds ui_goto_page/ui_set_active_field/ui_set_active_tab/
    # ui_set_active_entity (P4 Task 9) — one browser side-channel tool now,
    # so one exempt entry replaces the four.
    "ui_focus": "ui side-channel; agent→UI only, CLI clients ignore",
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

_TOOL_HTTP_MAP: dict[tuple[str, str | None], tuple[str, str]] = {
    # Project lifecycle
    ("create_project", None):             ("POST",   r"^/lab/projects$"),
    ("delete_project", None):             ("DELETE", r"^/lab/projects/\{slug\}$"),
    ("rename_project", None):             ("POST",   r"^/lab/projects/\{slug\}/rename$"),
    # Recycle bin — workspace-scoped (a deleted project lives here too), so
    # neither form takes a slug.
    ("list_trash", None):                 ("GET",    r"^/lab/trash$"),
    # Was exempt while it only answered for one doc ("CLI knows its own
    # pointer"). The set form answers "which docs did the run miss", which a
    # headless client cannot derive without re-implementing the join.
    ("get_surface_state", None):          ("GET",    r"^/lab/projects/\{slug\}/surface/\{surface\}$"),
    ("restore_from_trash", None):         ("POST",   r"^/lab/trash/\{entry\}/restore$"),
    # Doc lifecycle — filename is a primary key, so both of these move the
    # doc's whole artifact set (see the tool definitions); they are not rm/mv.
    # Retiring a memory note is more than a file op (body → _trash/, index line
    # dropped with it), so it is a verb; reading/writing notes needs no route
    # because ws_read/ws_write already cover plain files. The project-scoped
    # form is the one mapped here — the team-scoped twin is the same tool with
    # `slug` omitted.
    ("forget_memory", None):              ("DELETE", r"^/lab/projects/\{slug\}/memory/\{note\}$"),
    ("delete_doc", None):                 ("DELETE", r"^/lab/projects/\{slug\}/docs/by-name/\{filename:path\}$"),
    ("rename_doc", None):                 ("POST",   r"^/lab/projects/\{slug\}/docs/by-name/\{filename:path\}/rename$"),
    ("fork_project", None):               ("POST",   r"^/lab/projects/fork$"),
    ("promote_chat_to_project", None):    ("POST",   r"^/lab/chats/\{chat_id\}/promote$"),
    ("promote_attachment_to_docs", None): ("POST",   r"^/lab/projects/\{slug\}/chats/\{chat_id\}/attachments/\{filename:path\}/promote$"),
    # Pro labeler
    ("label_docs", None):         ("POST", r"^/lab/projects/\{slug\}/label_docs$"),
    # Project LLM-role config (/config surface). `get_project_config` folds in
    # `get_labeler_config` (P4 Task 5) — it already existed as its own tool
    # with its own route, so the merge carries TWO ops: its own pre-existing
    # default op (relabeled "config", not None, so it's distinguishable from
    # the newly absorbed "labeler") plus the absorbed route. See
    # test_merged_tools_map_every_op_to_its_own_route for why this means 2
    # ops for only 1 swallowed name.
    ("get_project_config", "config"):  ("GET", r"^/lab/projects/\{slug\}/config$"),
    ("get_project_config", "labeler"): ("GET", r"^/lab/projects/\{slug\}/labeler_config$"),
    # `set_model` folds 4 byte-identical (slug, model_id) setters into one
    # tool (P4 Task 4). REST already expresses the op as the resource, so the
    # HTTP side deliberately does NOT merge: one (tool, op) pair per route,
    # never an `op` query parameter. The four routes are unchanged.
    ("set_model", "labeler"):   ("POST", r"^/lab/projects/\{slug\}/labeler_model$"),
    ("set_model", "translate"): ("PUT",  r"^/lab/projects/\{slug\}/translate_model$"),
    ("set_model", "proposer"):  ("PUT",  r"^/lab/projects/\{slug\}/proposer_model$"),
    ("set_model", "extract"):   ("PUT",  r"^/lab/projects/\{slug\}/models/active$"),
    # Doc vision — both tools surface through the shared docs by-name page
    # render route (PDF→PNG / image bytes). The route doesn't take a
    # ``page`` body arg by name (it's part of the URL), but the byte-on-the-
    # wire output is what `read_doc_image` ships inline as base64.
    ("pdf_render_page", None): ("GET", r"^/lab/projects/\{slug\}/docs/by-name/\{filename:path\}/pages/\{page\}$"),
    ("read_doc_image", None):  ("GET", r"^/lab/projects/\{slug\}/docs/by-name/\{filename:path\}/pages/\{page\}$"),
    ("extract_textlayer", None): ("GET", r"^/lab/projects/\{slug\}/docs/by-name/\{filename:path\}/textlayer$"),
    ("translate_page", None):    ("POST", r"^/lab/projects/\{slug\}/docs/by-name/\{filename:path\}/translate$"),
    # Schema axes
    ("derive_schema", None):      ("POST", r"^/lab/projects/\{slug\}/schema/derive$"),
    ("write_schema", None):       ("POST", r"^/lab/projects/\{slug\}/schema$"),
    ("import_schema_from_yaml", None): ("POST", r"^/lab/projects/\{slug\}/chats/\{chat_id\}/attachments/\{filename:path\}/import-schema$"),
    ("add_model", None):            ("POST", r"^/lab/projects/\{slug\}/models$"),
    ("switch_active_prompt", None): ("POST", r"^/lab/projects/\{slug\}/prompts/\{prompt_id\}/activate$"),
    # Experiments
    ("create_experiment", None):       ("POST", r"^/lab/projects/\{slug\}/experiments$"),
    ("run_experiment_eval", None):     ("POST", r"^/lab/projects/\{slug\}/experiments/\{experiment_id\}/eval$"),
    ("promote_experiment", None):      ("POST", r"^/lab/projects/\{slug\}/experiments/\{experiment_id\}/promote$"),
    # Extract + score + readiness + contract-diff. `extract` folds
    # extract_one + extract_with_experiment (P4 Task 6) — the two hottest
    # tools in the system (147 + 53 recorded calls), differing by exactly one
    # optional argument. REST already expresses the op as the resource, so
    # the HTTP side deliberately does NOT merge: both pre-existing routes
    # stay exactly as they were, now keyed by op instead of by tool name.
    ("extract", "active"):     ("POST", r"^/lab/projects/\{slug\}/extract$"),
    ("extract", "experiment"): ("POST", r"^/lab/projects/\{slug\}/experiments/\{experiment_id\}/predictions/\{filename:path\}$"),
    ("save_reviewed", None):   ("POST", r"^/lab/projects/\{slug\}/reviewed/\{filename:path\}$"),
    # `score` folds score_audit + score_match (P4 Task 7) — same posture as
    # `extract`: REST already expresses the op as the resource, so the HTTP
    # side deliberately does NOT merge (note the GET/POST asymmetry across the
    # three routes stays — that predates the tool merge and is correct).
    ("score", "extract"):      ("POST", r"^/lab/projects/\{slug\}/score$"),
    ("score", "audit"):        ("POST", r"^/lab/projects/\{slug\}/audit-score$"),
    ("score", "match"):        ("GET",  r"^/lab/match/projects/\{slug\}/score$"),
    ("readiness_check", None): ("GET",  r"^/lab/projects/\{slug\}/readiness$"),
    ("contract_diff", None):   ("GET",  r"^/lab/projects/\{slug\}/contract-diff$"),
    # Bench leaderboard (project-level horizontal view of prompt × model evals).
    # Both forms thin-delegate to `app.services.bench.compute_bench`.
    ("bench_view", None):      ("GET",  r"^/lab/projects/\{slug\}/bench$"),
    # Document matching (reconciliation) — app/api/routes/match.py.
    ("create_match_project", None): ("POST", r"^/lab/match/projects$"),
    ("write_match_prompt", None):   ("PUT",  r"^/lab/match/projects/\{slug\}/prompt$"),
    ("run_match", None):            ("POST", r"^/lab/match/projects/\{slug\}/run$"),
    ("save_reviewed_match", None):  ("POST", r"^/lab/match/projects/\{slug\}/reviewed$"),
    ("write_audit_rules", None):    ("PUT",  r"^/lab/projects/\{slug\}/audit-rules$"),
    ("run_audit", None):            ("POST", r"^/lab/projects/\{slug\}/audit$"),
    ("read_audit_report", None):    ("GET",  r"^/lab/projects/\{slug\}/audit/latest$"),
    # B4 board render — annotated evidence images (pixels + rule text only;
    # the board-notes GET/PUT siblings are render-layer persistence and stay
    # route-without-tool, same as locate / locate-quotes). `render_board`
    # folds render_audit_board + render_review_board (P4 Task 10) — same
    # posture as `extract`/`score`/`control_job`/`history`: REST already
    # expresses the op as the resource, so the HTTP side deliberately does
    # NOT merge; both pre-existing routes stay exactly as they were, now
    # keyed by op instead of by tool name.
    ("render_board", "audit"):   ("GET",  r"^/lab/projects/\{slug\}/audit/board-render$"),
    ("render_board", "review"):  ("GET",  r"^/lab/projects/\{slug\}/review/board-render$"),
    ("save_reviewed_audit", None):  ("PUT",  r"^/lab/projects/\{slug\}/audit-review$"),
    # Publish + keys
    ("freeze_version", None): ("POST", r"^/lab/projects/\{slug\}/versions/freeze$"),
    ("issue_api_key", None):  ("POST", r"^/lab/keys$"),
    # Jobs. `control_job` folds pause/resume/cancel_job (P4 Task 8) — same
    # posture as `extract`/`score`: REST already expresses the op as the
    # resource, so the HTTP side deliberately does NOT merge. The three
    # routes are unchanged, only keyed by op instead of by tool name.
    ("start_job", None):     ("POST", r"^/lab/jobs$"),
    ("get_job", None):       ("GET",  r"^/lab/jobs/\{job_id\}$"),
    ("control_job", "pause"):  ("POST", r"^/lab/jobs/\{job_id\}/pause$"),
    ("control_job", "resume"): ("POST", r"^/lab/jobs/\{job_id\}/resume$"),
    ("control_job", "cancel"): ("POST", r"^/lab/jobs/\{job_id\}/cancel$"),
    # Version history (per-team git timeline). `history` folds log/diff (P4
    # Task 11, both read-only); `history_restore` mutates and stays its own
    # tool/route — same posture as `set_model` not merging on the HTTP side.
    ("history", "log"):        ("GET",  r"^/lab/history$"),
    ("history", "diff"):       ("GET",  r"^/lab/history/diff$"),
    ("history_restore", None): ("POST", r"^/lab/history/restore$"),
    # Headless discovery tools — registered only on the stdio/remote MCP
    # surface (build_emerge_mcp(headless=True)); the in-session chat agent
    # discovers via built-in Bash/Read instead. Their HTTP twins predate the
    # Step B wrapper cut and are still live, so the dual-form contract holds.
    ("list_projects", None): ("GET", r"^/lab/projects$"),
    ("list_docs", None):     ("GET", r"^/lab/projects/\{slug\}/docs$"),
    # read_prompt returns the active prompt (schema + global_notes) — its twin is
    # the active-prompt route, NOT schema/raw (which is fields-only YAML).
    ("read_prompt", None):   ("GET", r"^/lab/projects/\{slug\}/prompts/active$"),
    # Workspace filesystem bus (headless): generic ws_* tools share their pure
    # logic with these team-scoped twins (app/api/routes/ws.py).
    ("ws_list", None):       ("GET", r"^/lab/ws/list$"),
    ("ws_read", None):       ("GET", r"^/lab/ws/read$"),
    ("ws_grep", None):       ("GET", r"^/lab/ws/grep$"),
    ("ws_write", None):      ("POST", r"^/lab/ws/write$"),
    ("ws_edit", None):       ("POST", r"^/lab/ws/edit$"),
    ("ws_move", None):       ("POST", r"^/lab/ws/move$"),
    # Binary data plane: the tool mints capability URLs; its twin is the authed
    # mint route. The unauthed redemption endpoint (/lab/upload/{token}) is the
    # data plane itself, not a tool twin.
    ("request_upload_url", None): ("POST", r"^/lab/upload-urls$"),
    # Outbound half of the same data plane (/lab/download/{token} is likewise
    # the unauthed data plane, not a twin).
    ("offer_download", None): ("POST", r"^/lab/download-urls$"),
    # Progressive disclosure: domain playbooks pulled on demand.
    ("read_skill", None):    ("GET", r"^/lab/skills/\{domain\}$"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _discover_tools() -> set[str]:
    """Tools ACTUALLY registered on the MCP server.

    Was: a regex over `__init__.py` source text. That measured the wrong thing —
    nine tools kept their `@tool` decorator (so the regex matched) while never
    reaching the `tools=[...]` list, so they had HTTP twins mapped here for
    functions no agent could call. Registration is the contract; source text is
    not. See test_tool_registration::test_every_decorated_tool_is_actually_registered.
    """
    from app.tools import registered_tool_names

    return set(registered_tool_names(headless=True))


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
    mapped = {tool_name for tool_name, _op in _TOOL_HTTP_MAP}
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
    for (tool_name, op), (expected_method, expected_pattern) in _TOOL_HTTP_MAP.items():
        pat = re.compile(expected_pattern)
        match = any(
            method == expected_method and pat.search(path)
            for method, path in sigs
        )
        if not match:
            label = tool_name if op is None else f"{tool_name}[{op}]"
            missing.append(f"{label}: expected {expected_method} {expected_pattern}")
    assert not missing, (
        "Tools declared in _TOOL_HTTP_MAP have no matching live route:\n  "
        + "\n  ".join(missing)
    )


def test_merged_tools_map_every_op_to_its_own_route() -> None:
    """Coverage floor for a merged tool: it must map at least as many
    ``(tool, op)`` rows in ``_TOOL_HTTP_MAP`` as the number of old names it
    swallowed.

    ``>=``, not ``==``: ``MERGED_TOOLS`` only names the OTHER tool names a
    merge swallowed, not the survivor's own name — a merge target that already
    existed as its own tool before the merge (``get_project_config`` absorbing
    ``get_labeler_config``) keeps its own pre-existing route as an extra op on
    top of what it swallowed, so its route count legitimately exceeds
    ``len(olds)``.

    What this catches: a swallowed name's route disappearing outright, which
    is the whole story for a fresh-name merge (e.g. ``set_model``, where
    ``olds`` accounts for every op the tool has).

    What this does NOT catch: for a survivor merge, the survivor's OWN
    pre-existing op can be dropped from ``_TOOL_HTTP_MAP`` and this assertion
    still passes — the swallowed name's row alone already satisfies
    ``len(ops) >= len(olds)``. (An earlier version of this docstring called
    the ``<`` case "the real bug this catches", which overclaimed: it is
    *a* bug this catches, not the only shape of route loss a survivor merge
    can suffer.)

    Keep the stakes calibrated: ``_TOOL_HTTP_MAP`` is a coverage LEDGER, not a
    runtime contract — nothing here is wired into request dispatch. A dropped
    row degrades documented tool↔route symmetry (the AI-native API promise
    that every tool is also reachable over HTTP); it cannot break the running
    app the way a bad route or handler would."""
    from app.tools._merged import MERGED_TOOLS

    for new, olds in MERGED_TOOLS.items():
        ops = {op for (tool, op) in _TOOL_HTTP_MAP if tool == new}
        if new in _HTTP_EXEMPT:
            # Fully HTTP-exempt merged tool (P4 Task 9: ui_focus) — the whole
            # family opted out of HTTP via one _HTTP_EXEMPT justification, so
            # there are zero routes to hit by design, not by omission. The
            # per-op floor below assumes the tool actually maps routes.
            assert not ops, (
                f"{new!r} is in _HTTP_EXEMPT but still has _TOOL_HTTP_MAP rows "
                f"{sorted(ops)} — exempt and mapped are mutually exclusive; a "
                f"partial leftover would hide a dropped route."
            )
            continue
        assert len(ops) >= len(olds), (
            f"{new!r} swallowed {len(olds)} ops but only maps {len(ops)} "
            f"routes: {sorted(ops)}"
        )
        assert None not in ops, (
            f"{new!r} is a multi-op tool but has a (name, None) row: a None op "
            f"means two ops were collapsed onto one key, hiding the loss."
        )


def test_exempt_entries_carry_justification() -> None:
    """Each _HTTP_EXEMPT entry must have a non-empty justification string so a
    future reader knows *why* the asymmetry is intentional."""
    blank = [k for k, v in _HTTP_EXEMPT.items() if not v.strip()]
    assert not blank, (
        f"_HTTP_EXEMPT entries missing justification: {blank}. Add a one-line "
        "comment-style reason explaining why this tool has no HTTP twin."
    )
