# emerge — Insights & Trap Notes

> Non-obvious "why we did it this way" notes. Each entry is a trap that cost real
> debugging time during M1/M2A. Future agents should consult this before changing
> the corresponding code path.

---

## 1. `can_use_tool` callback is mandatory; `allowed_tools` alone is NOT enforced

**Where:** `backend/app/chat/service.py`

**The trap:** `ClaudeAgentOptions` accepts `allowed_tools=["mcp__emerge_tools__*"]`,
which looks like an allowlist. It is **not** under the default `permission_mode='auto'`
— the SDK auto-approves every tool call without consulting the list. During M1
dogfood, the agent went off the rails and used `Bash`/`Glob`/`Read`/`Grep` to
spelunk our own backend source code looking for a Gemini schema bug.

**The fix that actually works:**

```python
permission_mode="default",
can_use_tool=_emerge_only_permission,   # async callback that hard-denies
allowed_tools=[f"{_EMERGE_TOOL_PREFIX}*"],   # belt-and-braces
```

`permission_mode="default"` makes the SDK consult `can_use_tool` for every
invocation. The callback returns `PermissionResultDeny` for anything not
matching `mcp__emerge_tools__*`.

**Don't change** unless you've confirmed the SDK semantics changed in a newer
release. Drop `can_use_tool` and the agent gets full Bash/Edit/Write again.

---

## 1.5. SDK CLI auto-allows cwd-local Reads before `can_use_tool` fires

**Where:** `backend/app/chat/service.py`, `backend/app/chat/sdk_settings.json`

**The trap:** Under SDK 0.1.77 + `permission_mode="default"`, the CLI subprocess pre-decides Read of any file under its cwd as "safe" and skips `can_use_tool`. M10 dogfood (2026-05-17) confirmed: agent Read `backend/.env` and printed real `CLAUDE_CODE_OAUTH_TOKEN` + `GOOGLE_API_KEY` into chat transcript despite our `_workspace_safety_gate` returning `PermissionResultDeny`.

**The fix that actually works (three-tier defense):**
1. **Hard deny via SDK settings file** (`sdk_settings.json`) — `Read(/**/.env)`, `Read(/**/*.key)`, `Bash(printenv*)` etc. The SDK CLI enforces these *before* callback. Pass via `settings=<path>` + `setting_sources=["project"]`. Use our checked-in file (not user-level), so INSIGHTS #2's foreign-MCP isolation still holds. The settings file itself is in the deny list (`Read/Write/Edit(/**/sdk_settings.json)`) so the agent can't lift its own restrictions.
2. **Dynamic ask via `can_use_tool`** — for cross-workspace reads, network ops, etc. The callback fires only for tools/paths the deny list didn't catch.
3. **`cwd=self.workspace.resolve()`** — aligns the SDK CLI's "trusted local dir" with our gate boundary. Belt-and-suspenders: even without the settings file, paths outside workspace force callback consultation.

**Don't change** unless you've reproduced a fresh `.env` Read in a new chat and confirmed it's still denied. The callback alone is NOT sufficient.

---

## 2. `setting_sources=[]` prevents inheritance of user-level hooks/MCPs

**Where:** `backend/app/chat/service.py`

**The trap:** Without `setting_sources=[]`, the SDK loads the host user's
Claude Code settings — including third-party MCP servers (chrome-devtools,
excalidraw, etc.) and `SessionStart` hooks. Symptoms in M1 dogfood: chat
flooded with `hook_started`/`hook_response`/`init` SystemMessages dumping
the user's `superpowers:using-superpowers` skill content as raw JSON.

**The fix:** keep `user` and `local` out of `setting_sources` so the host's
`~/.claude/settings.json` and `.claude/settings.local.json` never feed in.

After INSIGHTS #1.5 we switched to `setting_sources=["project"]` (was `[]`)
to load our checked-in `backend/app/chat/sdk_settings.json` via the explicit
`settings=<path>` option. That file lives inside our repo, NOT in the user's
home or any auto-discovered project root, so the foreign-MCP / SessionStart
hook isolation this insight describes is preserved.

**Don't add** `"user"` or `"local"` to `setting_sources` — those are how
chrome-devtools / excalidraw MCPs and `SessionStart` hooks would re-enter
the chat stream. The only acceptable widening is loading another
emerge-controlled file via `settings=...`.

---

## 3. `CLAUDE_PROXY` (SOCKS5) leaks into Google httpx via `HTTPS_PROXY`

**Where:** `backend/app/provider/google.py`, `backend/app/provider/anthropic.py`

**The trap:** Some users set `CLAUDE_PROXY=socks5://...` in their `.env` so the
Claude SDK can reach `api.anthropic.com` through a tunnel. We previously copied
`CLAUDE_PROXY` → `HTTPS_PROXY` at chat-service startup. **httpx then picked it up
inside Google's `genai.Client`**, which doesn't have `socksio` installed →
`ImportError: Using SOCKS proxy, but the 'socksio' package is not installed.`

**The fix:** Both extract providers default to `trust_env=False` and accept
an explicit optional `proxy=` parameter. Factory reads `GOOGLE_PROXY` /
`ANTHROPIC_PROXY` from env separately. The Claude-side `CLAUDE_PROXY` is
isolated to the agent SDK's process env.

```python
# google.py
client_args: dict[str, Any] = {"trust_env": False}
if proxy:
    client_args["proxy"] = proxy
self._client = genai.Client(
    api_key=api_key,
    http_options=HttpOptions(client_args=client_args, async_client_args=client_args),
)
```

**Don't simplify** by routing all extract through `HTTPS_PROXY` — extract
and agent need separate proxy configs, by design.

---

## 4. Gemini rejects `additionalProperties` in `response_schema`

**Where:** `backend/app/tools/extract.py` `_build_response_schema`

**The trap:** v1 schema had `_evidence` declared as
`{"type": "array", "items": {"type": "object", "additionalProperties": {"type": ["integer", "null"]}}}`
to allow arbitrary field-name keys. Gemini's OpenAPI 3.0 dialect rejects
`additionalProperties` outright.

**The fix:** drop `_evidence` from the formal `response_schema`. The system
prompt still asks the model to emit it, and `ExtractionOutput.evidence` is
`Optional` so it gracefully degrades when absent.

**Future:** if M2C wants strict-shape `_evidence`, list each field name
explicitly with `{"type": "integer", "nullable": true}` (OpenAPI 3.0 form,
not JSON Schema's `["integer", "null"]` array form).

---

## 5. `pydantic-settings` reads `.env` but does NOT push to `os.environ`

**Where:** `backend/app/main.py`

**The trap:** Settings read `EMERGE_*` vars via `pydantic-settings`'s
`env_file` mechanism. Other libraries that read `os.environ` directly
(`claude_agent_sdk` for `CLAUDE_CODE_OAUTH_TOKEN`, `google.genai` for
`GOOGLE_API_KEY`, our provider factory for `GOOGLE_PROXY`) saw nothing.
M1 dogfood crashed with `ValueError: No API key was provided`.

**The fix:** `load_dotenv(Path(__file__).resolve().parent.parent / ".env")`
at the very top of `main.py`, before any module imports that touch env.

**Don't remove** the `load_dotenv` call thinking pydantic-settings
covers it. They're orthogonal.

---

## 6. SSE wire format may use CRLF line endings

**Where:** `frontend/src/lib/sse.ts`

**The trap:** `sse_starlette` emits `\r\n` line endings on the wire (per
spec, both `\n` and `\r\n` are valid SSE separators). Our `streamSSE`
reader was splitting on `\n\n` only. Chrome under Vite proxy delivered
the entire SSE body as one chunk; the parser dropped every event.

**The fix:** before splitting, normalize:
```ts
buf += decoder.decode(value, { stream: true })
// then in the parse loop:
const block = buf.slice(0, idx)
// where idx = buf.indexOf('\n\n') after this normalization:
buf = buf.replace(/\r\n/g, '\n')
```

**Don't** assume the SSE producer is in our control. Always normalize CRLF
on the consumer side.

---

## 7. SDK surfaces each tool result TWICE (`ToolResultBlock` + `UserMessage` echo) — emit once, pair to the call by `tool_use_id`

**Where:** `backend/app/chat/service.py` `_events_from_message`; frontend `frontend/src/stores/chat.ts` `handleToolResult`.

**The trap:** The Claude Agent SDK reports a tool's result in two places — a `ToolResultBlock` inside `AssistantMessage.content`, AND a `UserMessage` echo whose `content` is `list[ToolResultBlock]` (with `tool_use_result` set). Neither carries `tool_name`, only `tool_use_id`. Two failure modes seen: (a) the original M1 design dropped both, leaving the frontend blind to tool output (`ToolCallCard` showed **empty buttons**); (b) naively streaming each as its own card double-renders every result.

**The fix (reversed the original drop, M2C T10):** `_events_from_message` emits ONE `tool_result` SSE event per block — `{tool_use_id, result_text, ok}` — from both the AssistantMessage `ToolResultBlock` path and the UserMessage echo path (plain-string UserMessage echoes are the user's own prompt, already logged at `chat_turn` entry → skipped). The frontend's `handleToolResult` finds the matching `tool_call` card by `tool_use_id` and folds the result INTO it (never a standalone card). This is what lets e.g. `JobProgressCard` read a `job_id` out of a tool result and subscribe to `/lab/jobs/{job_id}/events`.

**Don't** revert to dropping the blocks (frontend goes blind), and don't emit a separate result card — always fold into the original call by `tool_use_id`.

---

## 8. Per-route `project_id` validation is mandatory; ASGI `%2F` routing is incidental

**Where:** every new HTTP route. Helper at `backend/app/api/routes/_safety.py`.

**The trap:** Without `safe_project_id()` validation, `%2E%2E` (URL-encoded
`..`) decodes to `..` and `project_dir(workspace, "..")` resolves to the
workspace's parent. Verified against a live server during M1 final review
— files written to `<workspace_parent>/docs/d_xxx.pdf`. Real arbitrary
write outside workspace.

**The fix:** every route handler that takes `project_id` from the URL must
call `safe_project_id(project_id)` first. Regex `^p_[a-z0-9]{12}$`.

**Don't** rely on FastAPI's ASGI routing to filter `%2F` — it does
incidentally (slashes split path), but `..` without slashes does NOT get
filtered. Defense in depth: validate at the handler.

---

## 9. Cross-store refresh on agent tool calls — drive it off the SSE tool stream, not the composer

**Where:** `frontend/src/stores/chat.ts` `handleToolResult` (runs on each `tool_result` SSE event — see #7).

**The trap:** When the agent mutates server state via chat (`create_project`, `upload_doc`, `save_reviewed`, `promote_experiment`, `freeze_version`, …), the affected panes (`useProjects` / `useDocs` / review tabs) show stale data until the user navigates away and back. M1 patched this by having `ChatPanel.onSubmit` manually call `refreshProjects()` + `refreshDocs()` after every send — fragile (fires regardless of what the tool actually did) and it coupled the composer to data stores.

**The fix (M9.3+):** `handleToolResult` switches on the completed tool's name and refreshes ONLY the affected store — `useDocs.getState().refresh(pid)` after doc-mutating tools, `useProjects.getState().refresh()` after project-mutating ones, etc. Refresh is now a pure function of which tool just finished; the composer no longer imports data stores, and the old `refreshProjects`/`refreshDocs` hooks are gone.

**Don't** re-add manual refresh calls to `ChatPanel`/composer for a new milestone (metrics, experiments, …) — add a case to `handleToolResult`'s tool-name switch instead. This is the same SSE-stream-driven model the turn-as-resource design (#14) relies on.

---

## 10. Messages starting with `/` are intercepted as Claude Code CLI slash commands

**Where:** `backend/app/chat/service.py` — `chat_turn`, the `prompt` passed to `client.query()`

**The trap:** `ClaudeSDKClient` runs the Claude Code CLI internally. The CLI treats
any input starting with `/` as a slash command. `/eval`, `/review`, `/extract` etc.
are all silently consumed by the CLI dispatcher with **no model response and no error**.
Symptoms: SSE stream emits only `user_acknowledged` → `turn_end` with nothing in between;
backend logs show `200 OK` with no errors; chat log only has the user line.

**The fix:** prepend a leading space when the user message starts with `/`:

```python
prompt = f" {user_message}" if user_message.startswith("/") else user_message
```

A leading space bypasses CLI command dispatch. The model receives ` /eval` and treats
it as plain text, matching the SKILL.md intent hints as expected.

**Don't remove** the space prefix. The model is robust to leading whitespace; the
CLI command dispatcher is not.

---

## 11. Chat continuity needs `ClaudeAgentOptions(resume=...)` + a session-id sidecar

**Where:** `backend/app/chat/service.py` — `chat_turn` / `_build_options`; `backend/app/chat/log.py` — `read_chat_session_id` / `write_chat_session_id`; sidecar at `chats/{chat_id}.meta.json`.

**The trap:** `chat_turn` opens a *fresh* `ClaudeSDKClient` every call and `client.query(prompt)` only carries the current message. Without `resume`, the agent has zero memory of prior turns — each user message is a brand-new session. The JSONL chat log (`chats/{chat_id}.jsonl`) is write-only, used purely for UI replay (`GET /lab/chats/{pid}/{cid}`); it is **never** fed back into the SDK.

**The fix:** persist the SDK `session_id` (read off every `ResultMessage`/`AssistantMessage`, or out of `SystemMessage(subtype="init").data`) to `chats/{chat_id}.meta.json` as `{"sdk_session_id": ...}` in the `finally` block, and pass it as `ClaudeAgentOptions(resume=<sdk_session_id>)` on the next turn.

**Self-heal:** if the resumed transcript is gone (`~/.claude/projects/...` was cleaned) the SDK raises at client startup — *before* any SSE event is yielded. Retry the turn **once** with `resume=None` **only if the resumed attempt failed before emitting anything user-visible** (`prev_sid is not None AND not yielded_any`): clear the dead sidecar (`write_chat_session_id(..., None)`), reset `latest_sid`/`yielded_any`, rebuild options with `resume=None`, re-run. A stale sidecar must never wedge the chat forever. But if the failure is *mid-stream* — a dropped connection or provider 5xx after `agent_text`/`tool_call` events were already streamed — do **not** retry (re-streaming would duplicate events on the frontend) and do **not** touch the sidecar (the session is fine; the failure was transient): re-raise so the existing `except Exception → agent_failure` SSE handler runs. When `prev_sid is None`, also don't retry — fall through to the same `agent_failure` SSE error.

**Don't** touch `setting_sources=[]` / `can_use_tool` / `disallowed_tools` while adding `resume` — they're independent and load-bearing (see #1, #2).

---

## 12. `SchemaField` is a deliberate Gemini JSON-Schema subset

`backend/app/schemas/schema_field.py` covers a minimum-useful Gemini OpenAPI-3.0 subset (`string / number / integer / boolean / object / array` + `string.format ∈ {date,date-time,time}` + `enum` on string). It does **not** model `minimum / maximum / minLength / maxLength / pattern / minItems / maxItems / prefixItems / additionalProperties`. These were deliberately dropped per SSU: in document extraction they add UI complexity for marginal accuracy gain. Before reintroducing any, ask: does the proposer or a user actually need it to express intent that `description` can't carry?

Legacy on-disk shapes (`type:"date"`, `type:"array<object>"+children`) are upgraded by a `model_validator(mode="before")` — no migration script, idempotent, transparent to disk readers. Add new legacy keys to the same normalizer rather than introducing a separate migrate step.

---

## 13. `reviewed/_pending/` is opaque because `Path.glob("*.json")` is non-recursive

**Where:** `backend/app/tools/score.py` `_load_reviewed`, `backend/app/tools/reviewed.py` `list_reviewed`.

**The trap:** The Pro Labeler (M10) writes drafts to `reviewed/_pending/{filename}.json`. The hard rule is that `score()`, `/improve`, `/publish`, and `readiness_check` must NEVER see these drafts as ground truth — only `reviewed/{filename}.json` (human-verified) counts. The mechanism that enforces this is **not** an explicit filter — it's that every prod path uses `rd.glob("*.json")` (non-recursive), which matches only files directly under `reviewed/`. The `_pending/` subdir is naturally invisible.

**Don't change** any of those globs to `**/*.json` or `rglob`. That would silently let pending drafts contaminate eval / readiness / improve. If you ever need recursive iteration, explicitly exclude `_pending/` and add a regression test asserting `n_reviewed = 0` after a `pre_label` run with no save.

**Note:** This same property is what M9.5 relied on for `chats/<chat_id>/attachments/` — workspace structure leans on non-recursive glob as a defense-in-depth filter, so think hard before promoting any of these to recursive.

---

## 14. Turn lifetime ≠ SSE lifetime — `enterProject` must NOT abort the in-flight stream

**Where:** `frontend/src/stores/chat.ts` lifecycle methods (`enterProject`, `switchChat`, `enterUnboundChat`, `newChat`, `deselect`); `backend/app/chat/turn_registry.py`; `backend/app/api/routes/turns.py` (M11).

**The trap:** prior to M11, switching project mid-turn left the SSE stream live → events bled into the new chat's `events[]` (we observed live 2026-05-19 on `太古_美国发票` → `荣耀_欧洲1` switch). The naive fix is to call `abort()` on every lifecycle switch — but that trades the bleed for "switch view = kill the backend agent task." That contradicts the AI-native API symmetry rule (a CLI client must be able to detach/reattach without affecting the running turn), and contradicts the digital-colleague stance generally.

**The shape that works (M11):**
1. Backend owns the turn via `TurnRegistry`. `POST /lab/chats/{cid}/turns` starts a turn (returns `turn_id`); `GET .../turns/{tid}/stream?after_offset=N` is a "tail -f" attach that any client can open / close / reopen.
2. Frontend persists `inflightTurnId` to `localStorage[turn:{cid}]` for the lifetime of the turn. Lifecycle methods (`enterProject` real-switch branch, etc.) call `_detachStream` — aborts the SSE GET only, does NOT touch `inflightTurnId`, does NOT call `cancelTurn`.
3. Re-entering the chat (`_maybeReattach` after hydrate) reads localStorage → `fetchTurnState` → if `running`, attaches a fresh stream with `after_offset = events.length`.
4. The Stop button (`cancel()`) is the ONLY frontend path that issues `POST .../cancel`. Closing SSE ≠ cancelling a turn.

**Don't change** the lifecycle methods to call `cancelTurn()` on switch — that's the "small fix" we rejected. And don't add a recursive auto-cancel in `_detachStream`. Detach is intentionally pure-client-side.

**Verified 2026-05-19** end-to-end: with a slow `/extract Airbus Invoice.pdf` turn running, switching to another project preserved the OLD chat's `turn:c_xxx` localStorage key; backend `turn_state` showed `status: running` with `last_offset` continuing to advance after the SSE GET disconnected; switching back fired `GET turn_state` + `GET stream?after_offset=N` and the full extract result rendered in the OLD chat.

---

## 15. tool ↔ HTTP dual-form is enforced by `test_symmetry_invariant.py`

**Where:** `backend/tests/unit/test_symmetry_invariant.py`; the contract it locks in is the AI-native API symmetry principle from memory `feedback_ai_native_api_symmetry` ("every lab action must be tool + HTTP dual-form; UI must be replaceable by Claude Code CLI agent without losing capability").

**The trap (M11 Phase B audit, 2026-05-19):** 13 tool-only actions had no HTTP counterpart. Each violated symmetry — a CLI agent driving HTTP could not do what the in-session agent could do via its tool surface. The asymmetry accumulated quietly across milestones (M9.3 added 7 experiment tools but only 4 HTTP routes; M10 added the labeler tools then back-filled HTTP routes in T6; M3 minted `issue_api_key` tool with no HTTP twin; etc.).

**The fix that actually works (M11 T14):** a single invariant test enumerates every `@tool("name", ...)` registration in `backend/app/tools/__init__.py` and asserts each is either mapped to a live `APIRoute` via `_TOOL_HTTP_MAP` or in `_HTTP_EXEMPT` with a one-line justification. The test runs in the regular unit suite, so opening a PR that adds a new tool without thinking about the HTTP twin trips CI immediately — catches the asymmetry at review time instead of months later when a CLI workflow surfaces it.

**Three known exempt categories (kept honest by the justification comment requirement):**
- `ui_*` (`ui_goto_page`, `ui_set_active_field`, `ui_set_active_tab`, `ui_set_active_entity`) — agent→UI side-channel; CLI clients silently ignore.
- `get_surface_state` — introspects the in-session frontend's review-mode pointer; a CLI caller already knows what doc it asked about.
- `ask_user` — the *request* half of an ask_user round-trip; the resolution half is `POST /lab/chats/{chat_id}/ask_user/{request_id}` (which IS the HTTP form a frontend / second CLI client uses to answer the question).
- `switch_active_prompt` — the existing `PUT /lab/projects/{slug}/prompts/active` does a *content edit* of the active prompt, not an id-flip; mapping the tool to it would encode a misleading contract. A real id-switch endpoint (`PUT /lab/projects/{slug}/prompts/active_id` with `{prompt_id: str}`, mirroring `PUT .../models/active`) is a Phase B follow-up.

**Don't** silently bypass the test by adding a new tool to `_HTTP_EXEMPT` without an explicit one-line reason — the third test (`test_exempt_entries_carry_justification`) refuses blank strings. Either add the route (preferred — Phase B route fillers in `2026-05-19-turn-as-resource.md` show the thin-delegate pattern: ~15–30 lines of body-validate + delegate to the same module function the tool wraps) or write down why the asymmetry is fundamental.

---

## 16. `m_default` is an immutable anchor id, NOT an alias for the active model

**Where:** `backend/app/tools/projects.py:create_project`, `backend/app/workspace/migrate.py`, `backend/app/tools/model.py`

**The trap:** `m_default` looks like a synonym for "whatever model the project is currently using" because (a) `create_project` writes both `models/m_default.json` AND sets `active_model_id="m_default"` in one go, (b) the file's `provider_model_id` carries the env-bootstrap value (`EMERGE_DEFAULT_EXTRACT_MODEL`), so on day-1 of a project you see `"m_default" → gemini-2.5-flash` and naturally read `m_default` as "the default Gemini Flash". Then a future agent — agent or human — sees `m_default` go stale (project active is now `m_geminipro`) and reaches for "rename `m_default` so it tracks active" or "delete `m_default` to clean up", which would silently destroy the experiment audit trail.

**What `m_default` actually is:** an immutable **anchor id**, not an alias.
- Created exactly once per project (by `create_project` for fresh projects, by `_migrate_to_m91` for legacy projects). The original `provider_model_id` it captured is whatever env was set at create time.
- Survives `switch_active_model` to other model ids (`m_geminipro`, `m_sonnet46`, etc.). The active flips; `m_default` stays where it is.
- Referenced from `_run` envelopes and experiment metadata (`experiments/<eid>/meta.json:model_id`) as a stable anchor. Renaming or deleting it breaks historical references — past `_run` stamps still say `model_id="m_default"` and need to find the file.

**Don't** rename `m_default` to track the active model id. **Don't** delete it on the assumption that `active_model_id` covers it. **Don't** change `create_project` to skip writing the `m_default` ModelConfig when env is unset — `read_active_model` would then crash on a fresh project. The label was deliberately decoupled from the env value (post-Phase 3 of `2026-05-27-default-extract-model-prompts-ev-eager-turing.md`): `"Default"` (no env-baked suffix) so the UI shows the same handle regardless of whether `EMERGE_DEFAULT_EXTRACT_MODEL` was changed; `provider_model_id` is what the user reads to know what's behind it.

---

## field-source-grounding: source is TEXT, locate is a render route

"Click a field, see where it came from in the PDF" is solved the LangExtract /
PyMuPDF way, not by asking the model for coordinates.

(a) Why `_evidence.source` is verbatim text, not coordinates. The Extract LLM
emits only the verbatim value + an optional `source` quote (<=120 chars,
original language, no rewriting). The backend then aligns that text against
PyMuPDF text-layer spans post-hoc to recover bbox rects (`app/tools/locate.py`).
We do NOT ask the model for bboxes: Gemini's native bbox output is unreliable
for document layout, and -- more fundamentally -- coordinates in a prompt
violate Software-3.0 (you teach via `description` / `global_notes`, never carry
positional geometry in the prompt). Text in, text out; geometry is recovered by
code (rapidfuzz fuzzy + `eval/normalize.py` type-aware equivalence).

(b) Why locate is an HTTP route, never a `@tool`. `FieldLocation.rects` are bbox
coordinates. If locate were an agent tool, those rects would land in the SDK
context and leak coordinates into the brain -- breaking the hard rule. So
`POST .../locate` is render-only (`app/api/routes/locate.py`), consumed by the
review viewer. The symmetry invariant only enforces "@tool => route"; a
route-without-tool is legitimate and needs no `_HTTP_EXEMPT` entry.

## locate auto-pan: driven by a request seq, NOT by overlay mount

Clicking a field pans the doc so its source rect centers (`block:'center'`,
no zoom). The scroll is fired from `LocateHighlight` — the only place that
already knows the rect's rendered geometry (handles fit/zoom/rotation for free
via `scrollIntoView`). The trap a "simplification" would re-introduce: driving
that scroll off the overlay **mounting** (i.e. scroll whenever the focused
page's highlight appears). That yanks the viewport when a far page lazy-loads
during ordinary manual scrolling. Instead the focus handler bumps a monotonic
`useLocate.scrollReq = {seq, path}`, and each page's highlight *claims* a seq
once (`consumedSeqRef`). So: (a) incidental lazy mounts never scroll — no new
seq; (b) an off-page target still pans after it finishes loading — the seq is
still unclaimed; (c) re-clicking the same field re-pans — new seq. Pages never
unmount (`loadedPages` only grows), so the per-page claim persists.

When a focused field has no locatable rect (`status:'none'` / no entry), there
is nothing to pan to — `PdfViewer` shows a bottom-center pane hint
(`.dv-locate-hint`, `review.locate.notFound`) so the reviewer stops hunting
page by page. `resolving` covers the sub-second window before `locate` resolves.

## locate perf: dateparser is O(spans) — gate + memoise, never remove

`/locate` on a 28-page × 14-entity doc took **>180s** (wedging the review pane).
Not OCR — textlayer sidecars were warm. cProfile pinned 84% on
`_date_equivalent → dateparser.parse`: a date-ish field that misses its
page-hint scans the WHOLE document, and the old code ran `dateparser.parse`
(~10ms, lazy-loads locale tables) on EVERY span of every scanned page, ×every
entity. 494 parses for 3 entities; it scales with spans×pages×date-fields×entities.

Two guards make it ~80× faster (180s → 2.3s) with ZERO match change (same
97/159 located on a fixed 3-entity input; 36 locate tests green):
- `_parse_date` = `lru_cache`’d dateparser. The same value parses against
  hundreds of spans and recurs across every entity — caching bounds parses to
  the count of UNIQUE strings, so cost stops scaling with entity count.
- `_DATE_GATE` / `_span_maybe_date`: a cheap regex pre-filter so only
  date-SHAPED spans reach dateparser. Deliberately inclusive (separator / CJK
  年月日 / month-word / bare yyyymmdd) so it never drops a span the unfiltered
  path matched. Do NOT narrow it to ASCII-only.

Also: `span_cache` is now hoisted to document scope (was per-entity), so a
multi-entity doc reads each page's textlayer sidecar once, not once-per-entity.

Still open (the click-path latency the user flagged): a COLD doc whose scanned
pages have no textlayer sidecar yet still triggers Gemini OCR on the first
locate/review. The right fix is to warm textlayer (incl. OCR) at upload/extract
time and persist it, so review only ever reads warm sidecars — bigger change
(touches the extract pipeline), not done here.

## locate focus/pan/highlight MUST scope by (entity, path), not path alone

A multi-entity doc carries the SAME leaf path once per entity — `invoiceNumber`
appears for all 14 invoices, each on its own page. The review highlight + the
click-to-pan resolve a field to its `FieldLocation`, and matching on `path`
alone always returns entity 0's occurrence → clicking entity 5's `invoiceNumber`
jumped to entity 0's page and ringed the wrong value. Fix: the locate store
carries `focusedEntity` alongside `focusedPath`; `LocateHighlight`,
`PdfViewer.focusStatus`, and `FieldEditor`'s click-time `find` all filter
`l.entity_index === focusedEntity && l.path === focusedPath`. `focusedEntity`
is the displayed `activeEntityIdx` (passed through `focus(path, entityIdx)`).
Note `activeField` (row highlight, review store) is SEPARATE from `focusedPath`
(locate, doc-pane) — they can desync; don't assume one implies the other.

## don't setTimeout-auto-dismiss a focus-derived hint inside its own effect

The "no source in document" pane hint first used `useEffect(... setLocateHint
('unlocated'); setTimeout(()=>setLocateHint(null), 2800) ...)`. The pill never
appeared: the timer (or its effect-cleanup) cleared the state almost immediately
under React's dev effect re-runs. The hint is a pure function of `focusStatus`,
so derive it — `const locateHint = focusStatus === 'unlocated' ? ... : null` —
no state, no timer. It then shows exactly while that field is the focused one and
clears when focus moves, which is also the better contract (the pill is the
answer to "where's the source?", so it lives as long as the question does).

## /locate must run OFF the event loop — its async reads don't actually await

Rapid doc-switching froze the whole backend: review-form GETs and the next
doc's locate hung ("加载中…" / "正在定位来源…" stuck). Root cause: `locate_fields`
is CPU-bound (rapidfuzz / clustering / dateparser) and its only "async" calls —
`extract_textlayer` on a WARM sidecar — are `json.loads(read_text())` with no
real `await` inside. So `await locate_fields(...)` runs start-to-finish without
ever yielding, blocking the single event loop for its full duration; a backlog
of switched-away locates blocked it for the sum. Fixes:
- the route runs locate via `asyncio.to_thread(lambda: asyncio.run(locate_fields
  (...)))` — a worker thread + fresh loop, so the main loop stays responsive.
- `_spans_for_page` passes `skip_ocr=True`: locate never makes the per-cold-page
  Gemini OCR call (multi-second, and a hard error when the OCR client is
  misconfigured). It reads warm sidecars + fitz only, so the threaded work is
  pure-CPU/file-IO (no provider client → safe across the fresh loop). The viewer
  still warms OCR sidecars via GET /textlayer; locate self-heals as pages warm.
  Caveat: on a genuinely-scanned doc whose pages the viewer hasn't shown yet,
  locate fitz-only under-matches those pages until they're warmed — acceptable
  for a best-effort render aid; electronic PDFs (fitz-readable) are unaffected.

## the locate render path is LLM-free — ground belongs in the extract pipeline

`loadFor` used to run a ground LLM pass (fetchGround) before locate whenever the
displayed blob carried no evidence, to mint verbatim source quotes for precise
highlights. But this is the click-to-pan render path: a render aid must never
block on an LLM. When the provider was slow/unreachable the ground call retried
the whole backoff window (~10s, then 500), stalling "正在定位来源…" — looking
exactly like a freeze. locate now calls fetchLocate directly with whatever
evidence already exists; no-evidence docs fall back to the (LLM-free) value
matcher, which is already capable. Producing source quotes is the extract/label
pipeline's job (warmed into the blob at creation), not a lazy review-time call.
`loadFor`'s `activeBacking` arg (the old ground cache target) is now ignored.

## locate needs a TEXT LAYER, not just `_evidence` — warm it or it's "完全没定位"

Migration completeness is two independent things and the obvious one hides the
other. `backfill_grounding.py` writes `_evidence` (page + verbatim source quote)
by sending the page IMAGE to the LLM — it never builds the text layer. But locate
aligns that source quote against **text-layer spans** to recover rects; the text
layer is built LAZILY the first time the viewer opens a doc (GET /textlayer →
`extract_textlayer`). So a migrated corpus nobody clicked through has `_evidence`
= full yet **zero spans → every field resolves to `none`** ("完全没定位"), and the
translate sidecar is likewise cold ("还要实时翻译" every open). Real numbers from
`invoice(发票)_海信日本`: 357/369 docs full-evidence, no text layer. `verify_grounding.py`
audits ONLY evidence and reports these as healthy — it can't see the gap;
`scripts/diagnose_doc_pipeline.py` adds the textlayer/translate dimension, and
`scripts/warm_textlayer.py` is the missing warm step (the "Still open" item the
locate-perf note flagged). Electronic pages warm via fitz for free (zero egress);
only scanned pages spend an OCR call — so warm fitz-first, OCR only on empty.

Two OCR traps the warm surfaced:
- **flash-lite (`default_translate_model`) emits truncated / malformed JSON on
  dense scanned pages** → the provider parse raises → `_ocr_extract_spans` returns
  `[]` → an "empty" sidecar that can NEVER locate. It is NOT a blank page (same
  page yields 82 spans on gemini-flash-latest). The lab doesn't budget tokens and
  the image upload (the real cost on a bandwidth-capped host) is identical across
  models, so a stronger OCR model is a free win — `extract_textlayer(..., ocr_model=)`
  / `warm_textlayer.py --model gemini-flash-latest`. bbox quality also improves,
  which is the same drift the original "highlight 上移" complaint was about.
- **`extract_textlayer`'s cache guard (`ocr_attempted` True → return cached)
  prevents re-OCR.** An empty-but-attempted sidecar short-circuits forever, so you
  can't upgrade flash-lite's empties to a better model by just re-running — you
  must DROP the sidecar first (`warm_textlayer.py --force`, which only ever unlinks
  a page that currently has no spans; good fitz/OCR pages are returned before it).

## multi-tenancy: team is a workspace SUBDIR, auth has an open↔tenant switch

Two non-obvious shapes from the Users & Teams milestone (2026-06-03) that a
future "simplification" would break:

(a) **Why team is `workspace_root/teams/{tid}/{slug}/`, not a `project.json`
field.** Isolation is then PHYSICAL (the agent's `cwd` sandbox auto-tightens to
the team dir — it literally can't `ls` another tenant), and the entire existing
machinery (`tools/`, `paths.py`, `chat/service.py` all take `workspace: Path`)
works UNCHANGED. The only edit was at the route layer: `settings.workspace_root`
→ `current_ws()`, fed by a router-level `dependencies=[Depends(bind_workspace)]`.
A `team_id` column would instead have forced a filter into every list path and
made slugs collide across tenants. Don't "flatten" the teams/ nesting back.

(b) **Open mode vs tenant mode (`store.auth_configured`).** While NO user
exists, `current_user` returns None and `bind_workspace` returns the flat root —
identical to pre-tenancy, zero auth. This is the ONLY reason the ~1000 existing
route tests (which never authenticate and write to `workspace/{slug}`) still
pass. The switch flips the instant `create_superuser` mints the first user.
Don't make auth unconditionally enforced — you'll 401 the whole legacy suite.
If you add a new `/lab/*` router, give it `dependencies=[Depends(bind_workspace)]`
and read the workspace via `current_ws()` (NOT `settings.workspace_root`), or it
silently serves the flat root and leaks across tenants in tenant mode.

(c) **`current_ws()` is a ContextVar set per-request by `bind_workspace`.** It's
read in the async handler and the resolved `Path` is passed BY VALUE into tools
/ `asyncio.to_thread` closures — never read the contextvar from inside a thread
or a detached turn task (it won't be set there; it falls back to root). Auth
data (`_auth/*`) and the prod keystore (`_keys.json`) live at the TRUE root and
are accessed via `settings.workspace_root`, never `current_ws()`.

---

## cleanup_orphan_projects is tenancy-aware — `teams/` is NOT an orphan

**Where:** `backend/app/workspace/orphans.py`, called on startup from `main.py`.

**The trap (cost: every tenant's every project, deleted on restart).** Orphan
cleanup's rule is "any non-`_`/`.` root dir lacking `project.json` is partial-
write debris → `shutil.rmtree` it". The tenancy milestone (2026-06-03) added
`workspace_root/teams/` as the new home for all tenant projects — and `teams`
is NOT `_`-prefixed and has no `project.json` of its own. So the very next
`./dev.sh -b restart` swept the **entire `teams/` tree**: every team, every
project, gone (rmtree, no DB, workspace is gitignored → unrecoverable). The
symptom was "logged in as superuser, my team sees zero projects, and the empty
`teams/{tid}/` has today's mtime". `migrate_to_tenancy` had correctly moved the
projects in at bootstrap; cleanup ate them on the next boot.

**The fix.** `teams/` is hard-exempt at the root, and we recurse exactly one
level into each `teams/{slug}/` to reap genuine orphans there — but never remove
a team dir itself (it's the durable tenant root even when empty). Any new non-
`_`-prefixed sentinel dir you add at the workspace root MUST be added to the
skip set here too, or it gets rmtree'd on the next boot. Don't "simplify" the
two-layer sweep back into a single flat-root loop.

**The deeper fix — soft-delete (`workspace/trash.py`).** The incident's root
lesson: with no DB, a `rmtree` of user data is unrecoverable, so don't do it.
Every delete path on user data (`delete_project`, `delete_experiment`, orphan
sweep) now `trash()`es — an atomic rename into `workspace/_trash/{ts}-{name}/`,
purged only after a 14-day retention by `cleanup_trash` on startup. `rmtree` is
allowed ONLY on derived caches that are immediately rebuilt (e.g.
`predictions/_draft/` in `promote`). `delete_project` specifically gains from
the move: the single rename IS the tombstone (live `project.json` vanishes
atomically, tripping the chat-log gate) AND keeps `project.json` in the trashed
copy — strictly better than the old unlink-then-rmtree which destroyed it.

---

## team workspace dir is named by `Team.slug`, not `t_…` id

**Where:** `backend/app/auth/store.py` (create_team), `auth/deps.py`
(bind_workspace), `mcp_server.py`, `workspace/migrate_team_dirs.py`.

The agent's cwd is its team workspace, so an opaque `teams/t_7fp7mzchoxff/` is
hostile to the colleague (`cd` into meaninglessness). Teams now mirror the
project model: the **directory** is `teams/{slug}/` (human-readable, CJK
preserved — `teams/荣耀/`), while the stable `t_…` **id** lives only inside
`teams.json` as the reference anchor (members, PATs, `active_team_id` all key off
it; a rename never moves the dir). `derive_slug` is shared via
`workspace/slug.py` (extracted from `tools/projects.py` so `auth/` doesn't depend
on `tools/`). `team_workspace_dir(root, dirname)` takes the **slug**, so every
caller resolves `team.slug` from the row (fallback `or team.id` only covers the
pre-backfill window). `migrate_team_dirs` runs on startup BEFORE the orphan
sweep: it backfills `slug` on legacy rows and renames `teams/{id}` → `teams/{slug}`
idempotently. If you add a path that needs a team workspace, resolve the slug —
never concat `teams/{team_id}`.

---

## prod global artifacts (`_published/`, `_keys.json`) live at the TRUE root

**Where:** `backend/app/tools/publish.py` (`freeze_version`, `issue_api_key`).

**The trap (tenant-mode publish silently broken).** The prod fast-path `POST
/v1/extract` is login-agnostic — it reads `published_path(settings.workspace_root)`
and validates keys against `get_keystore(settings.workspace_root)`, i.e. the TRUE
root. But the lab/agent WRITE side (`freeze_version`, `issue_api_key`) ran with
the *effective* workspace (`current_ws()` = `teams/{slug}/` in tenant mode), so a
frozen artifact + its key landed under the team dir. Result: in tenant mode every
publish was invisible to prod — `/v1/extract` returned 404 (artifact) / 401 (key)
for something the agent had just "published". Open mode hid it (root == effective
workspace), so it only bit once a superuser existed.

**The fix.** `_published/` and `_keys.json` are GLOBAL (CLAUDE.md), same class as
`_auth/`. `freeze_version` now writes the artifact to `get_settings().workspace_root`
(while still READING the project from its team `workspace`); `issue_api_key` took
the realization to its logical end — it dropped its `workspace` param entirely
(a keystore is never team-scoped) and always uses the true root. The routes were
already correct (`settings.workspace_root`); only the tool side deviated. When you
add anything prod reads, write it to the true root, not `current_ws()`.

---

## Spine tree: never name a component class after a Tailwind utility word (`inline`)

**Where:** `frontend/src/components/Spine/FSSpine.tsx` + `spine.css` (the inline-accordion file tree under each project).

**The trap.** The expandable file tree used `className="tree inline"` and styled it via `.fs .tree.inline{...}` — but that rule only set margin/border/padding, never `display`. Tailwind v3 ships a core utility `.inline{display:inline}`, which matched the same element and silently turned the whole tree into an **inline box**. Two symptoms, one cause:
- a ~24px phantom vertical gap between the project row and `docs/` (inline line-box height above the block children the inline box was illegally wrapping), and
- the rail's `margin-left` indentation not applying (inline boxes don't lay out block children under their own left margin), so `docs/` sat at x≈0 instead of nesting.

**Why it hid for so long / from static repro.** A standalone HTML harness that doesn't import Tailwind has no `.inline` rule, so the tree defaults to `display:block` and looks perfect. It only breaks in the real app where Tailwind's reset+utilities are loaded. Confirmed live via DOM probe: `getComputedStyle(tree).display === "inline"`, matched rule `.inline` from the injected `<style>` tag.

**The fix.** Rename the modifier to a non-utility word: `className="tree nested"`, `.fs .tree.nested{display:block;...}` (kept an explicit `display:block` as belt-and-braces). Clean hierarchy is now project 16 → dir 29 → file 43 px.

**Don't** reuse single-word class names that collide with Tailwind utilities (`inline`, `block`, `hidden`, `fixed`, `static`, `relative`, `grid`, `flex`, `table`, `container`, …). **Latent twin:** `frontend/src/index.css` `.pub-stage.inline` has the same shape (sets `position` but not `display`) — audit it if pub-stage layout ever looks off.

---

## turn wrapper task: a sync-raising `runner_factory()` used to wedge the chat forever

**Where:** `backend/app/chat/turn_registry.py::_run_turn` + the `_FakeChatService` stubs in `tests/integration/test_chat_turns_lifecycle.py` / `test_turns_reattach_after_finish.py`.

**The trap (two layers, 2026-06-10 full-suite deadlock).**
1. `_run_turn` called `runner = runner_factory()` **outside** its try block. The factory executes `ChatService.chat_turn(...)` — code that can raise *synchronously* (the real method is an async-gen so it usually can't, but any wrapper/mock that isn't a generator function runs its body immediately). A sync raise killed the task with `entry.status` stuck at `RUNNING` and **no sentinel broadcast**: every SSE subscriber blocked on `queue.get()` forever, and the chat answered 409 `turn_already_active` until backend restart. In tests this looked like `TestClient` hanging in a portal future at 0% CPU — un-interruptible by pytest-timeout's signal mode (the portal `lock.acquire` never runs Python signal handlers; only thread mode + xdist worker isolation survives it).
2. The trigger was a **mock signature drift**: commit `5829668` added `interface=` to the `svc.chat_turn(...)` call in `turns.py::_start_turn_for`, but the two integration-test fakes' `chat_turn` signatures weren't updated → `TypeError` inside the factory → layer 1 swallowed it silently.

**Debugging lesson.** The obvious suspect (starlette/sse-starlette/httpx version drift from the 06-09 `uv.lock` refresh) was **disproven** by `uv run --with` overlay bisection — old versions deadlocked identically. What worked: gc-walk all `asyncio.Task`s *and async generators* in the hung process (`task.get_stack()` shows one frame; walk `cr_await`/`ag_frame` chains for the real suspension point). The dump showed `turn-xxx done=True` next to `gen()` parked at `await queue.get()` — i.e. "task finished but never signalled", which points straight at the wrapper's exception path.

**Don't:**
- move `runner_factory()` back out of the try in `_run_turn` ("it's just a constructor call" — it isn't, it runs service code);
- add a kwarg to `ChatService.chat_turn` without grepping `tests/**` for fake `chat_turn` signatures (regression pin: `test_factory_exception_flips_error_and_sends_sentinel` keeps the wedge from coming back even if a fake drifts again);
- trust pytest-timeout `signal` mode to break a TestClient-portal hang — full runs use `-n 8 --dist loadfile` so a hung worker dies alone.

---

## Audit rules must be group-invariant — the agent will bake instance values in

**Where:** `app/skills/emerge_extractor.md` §audit `write_audit_rules` guidance; `app/tools/audit_run.py`.

**The trap (2026-06-10 百胜audit1 dogfood).** User gave generic relational rules ("完工报告抬头与报价单抬头关键字一致"). The agent `read_doc_image`'d the docs to sharpen them — legitimate authoring assistance — but then wrote the CURRENT group's literals INTO the rules ("需包含 Y25、2月疯四、KFC…" + the exact 品项类别 list). Those rules pass today and wrongly fail next month's "3月" doc group: the rule was overfitted to one sample. Rules are the project's audit contract across ALL future groups; instance values (titles, amounts, dates) are runtime facts the judge reads off the images.

**The discipline (now in the skill):** before writing a rule ask "does this hold for the NEXT doc group?" Write roles + relations; only user-stated global constants (fixed 甲方 name, red-seal requirement) may be literal. Reading docs to understand rule intent is fine — pinning what you saw into rule text is not.

**Why this matters doubly:** rules are versioned prompt + the `score_audit` regression target. An instance-pinned rule poisons both: it scores 100% on the group it was written from (self-fulfilling) and regresses on every other group.

---

## When to add an entry here

**Add an entry when:**
- A bug took >1 round to debug and the fix is non-obvious from reading the code
- A library/SDK semantics differs from documentation (yours or theirs)
- A spec invariant has a non-trivial enforcement (atomic write, flock, can_use_tool, ...)
- A future agent could plausibly "simplify" the code and re-introduce the trap

**Don't** add entries for:
- Trivial bugs fixed in one commit
- Style preferences
- "How do I run tests" — that's CLAUDE.md
