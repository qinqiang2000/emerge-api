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

## 2. `setting_sources=[]` prevents inheritance of user-level hooks/MCPs

**Where:** `backend/app/chat/service.py`

**The trap:** Without `setting_sources=[]`, the SDK loads the host user's
Claude Code settings — including third-party MCP servers (chrome-devtools,
excalidraw, etc.) and `SessionStart` hooks. Symptoms in M1 dogfood: chat
flooded with `hook_started`/`hook_response`/`init` SystemMessages dumping
the user's `superpowers:using-superpowers` skill content as raw JSON.

**The fix:** `setting_sources=[]` in `ClaudeAgentOptions`. This means
**none** of `user`/`project`/`local` settings are read — only what we
pass explicitly via `mcp_servers={"emerge_tools": ...}` and `system_prompt=...`.

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

## 7. SDK echoes `ToolResultBlock` and `UserMessage.tool_use_result`; both render as empty cards

**Where:** `backend/app/chat/service.py` `_events_from_message`

**The trap:** The Claude Agent SDK emits `ToolUseBlock` (the call) AND a
later `ToolResultBlock` (the result, with no `tool_name`, only `tool_use_id`)
AND a `UserMessage` echo with `tool_use_result` set. We initially streamed
all three to the frontend as `tool_call` events. The frontend's
`ToolCallCard` rendered the result-only events as **empty buttons** (a11y
read them as "(no content)").

**The fix:** drop both `ToolResultBlock` and `UserMessage.tool_use_result`
echoes in `_events_from_message`. The original `ToolUseBlock` card is
sufficient; the result content is consumed by the model on its next turn.

**Future:** when M2C/M3 wants result content shown (e.g. inline tool
output for transparency), pair via `tool_use_id` and fold the result into
the original card — don't emit a separate event.

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

## 9. Frontend cross-store refresh holes

**Where:** `frontend/src/components/Chat/ChatPanel.tsx`

**The trap:** When the agent calls `save_reviewed` / `upload_doc` via chat,
the right-pane `DocList` doesn't auto-refresh. Stale badges. M1 had this
for projects (chat creates project, list doesn't refresh until user
navigates away/back). M2A inherited it for docs.

**The current patch:** `ChatPanel.onSubmit` explicitly calls
`refreshProjects()` AND `if (selectedId) await refreshDocs(selectedId)`
after each chat send.

**The cleaner future fix:** emit a `tool_done` SSE event that stores
subscribe to. Add this in M2C when `tool_use_id`/`ToolResultBlock` pairing
is reworked.

**Don't** add another store dependency to `ChatPanel` for the next
milestone (e.g. metrics) — wire it to the SSE stream instead.

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

## When to add an entry here

- A bug took >1 round to debug and the fix is non-obvious from reading the code
- A library/SDK semantics differs from documentation (yours or theirs)
- A spec invariant has a non-trivial enforcement (atomic write, flock, can_use_tool, ...)
- A future agent could plausibly "simplify" the code and re-introduce the trap

**Don't** add entries for:
- Trivial bugs fixed in one commit
- Style preferences
- "How do I run tests" — that's CLAUDE.md
