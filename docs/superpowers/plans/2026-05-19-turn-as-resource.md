# M11 — Turn as first-class resource (attach/detach SSE)

> **For agentic workers:** execute task-by-task. Each task is self-contained
> (files + code sketch + test command + commit message). Run the test step
> at the end of every task; commit only when green. Stop and report on
> repeated failures.

**Goal:** decouple agent turn lifetime from the SSE request lifetime. A turn
becomes a long-lived addressable resource owned by the backend; the SSE
stream becomes a "tail -f" subscription that any client can attach to /
detach from / re-attach to without affecting the turn.

**Why this milestone, now**: emerge's AI-native API symmetry principle
(memory `feedback_ai_native_api_symmetry`) says the UI must be replaceable
by a Claude Code CLI agent without losing capability. Today's wiring fails
that test in two ways:

1. **Switching project mid-turn bleeds events into the wrong chat.** The
   in-flight SSE keeps appending to `events[]` after `enterProject` flipped
   `chatId`. Pre-existing bug, surfaced live 2026-05-19.
2. **CLI clients can't detach.** `POST /lab/chat` ties the entire agent
   loop to the HTTP connection. A CLI user closing their terminal kills
   the turn. There's no `tail -f`, no reconnect, no "watch from a second
   pane." This is the opposite of the "digital colleague" stance — it's
   pure RPC.

Fixing #1 with a cancel-on-switch patch would be ~30 lines but would
double down on #2. This plan does the symmetric thing instead.

**Architecture (in one picture):**

```
client A ───▶ POST /lab/chats/{cid}/turns ─┐
                                            ▼
                                  ┌──────────────────┐
                                  │  TurnRegistry    │
                                  │  cid → TurnEntry │
                                  │  - turn_id       │
                                  │  - task          │
                                  │  - subscribers[] │
                                  └──────────────────┘
                                            │
                                  ┌─────────┴──────────┐
                                  ▼                    ▼
                          events.jsonl         in-memory broadcast
                          (persisted)          (live subscribers)
                                            ▲
client A ───▶ GET .../turns/{tid}/stream?after=N ─┘
client B ───▶ GET .../turns/{tid}/stream?after=N ─┘  (multi-client OK)

client A disconnects (switch view, close laptop) → subscriber removed.
Turn keeps running. client A returns → GET .../turn_state → re-attach
with offset = last persisted line.
```

One active turn per chat (matches current semantics; no concurrent turns
on the same chat). Turn registry is in-memory only — surviving a backend
restart is out of scope; events.jsonl is still the durable record.

**Tech stack:** FastAPI + sse_starlette + asyncio (backend), React 19 +
Zustand (frontend). Backend test command:
`cd backend && uv run pytest <path> -v`. Frontend test command:
`cd frontend && npm test -- <pattern>` and `cd frontend && npx tsc --noEmit`.

**Reference docs:**
- Predecessor surface: M8 (chat history), M9.5 (paste-attachments), `2026-05-19-conversations-vs-projects.md` (chat first-class storage)
- INSIGHTS to respect: #1 / #1.5 (workspace safety gate + sdk_settings), #4 (Gemini schema), #9 (frontend cross-store refresh)
- CLAUDE.md hard rules unchanged — no schema/skill changes here

**Scope boundary — explicitly OUT of scope:**
- Cross-restart turn resumption (registry is in-memory; if backend restarts mid-turn, that turn is lost — same as today, just with a clearer "status: orphaned" state on reattach).
- More than one active turn per chat (one at a time, queued or rejected).
- Turn-level audit log separate from events.jsonl (jsonl is the audit trail; turn registry is operational state).
- Backpressure / queue size limits (asyncio.Queue unbounded; events are small).
- WebSocket transport (SSE is good enough; keep the surface narrow).

---

## File map

**New files (backend):**
- `backend/app/chat/turn_registry.py` — `TurnRegistry`, `TurnEntry`, `TurnStatus` enum
- `backend/app/api/routes/turns.py` — new `/lab/chats/{cid}/turns*` routes
- `backend/tests/unit/test_turn_registry.py`
- `backend/tests/integration/test_chat_turns_lifecycle.py`

**New files (frontend):**
- `frontend/src/lib/turn.ts` — `startTurn`, `attachStream`, `cancelTurn`, `fetchTurnState`
- `frontend/src/stores/chat.test.ts` — store-level unit tests for the split

**Modified (backend):**
- `backend/app/api/routes/chat.py` — keep `/lab/chat` and `/lab/chats/{cid}/turn` as compat shims that delegate to the new flow (POST start + immediate stream attach), so we don't break older clients during cutover.
- `backend/app/api/routes/__init__.py` — register `turns` router.

**Modified (frontend):**
- `frontend/src/stores/chat.ts` — split `send` into `startTurn` + `attachStream`; lifecycle methods (`enterProject`, `switchChat`, `enterUnboundChat`, `newChat`, `deselect`) detach the stream instead of letting it leak; per-chat `inflightTurnId` so re-entering re-attaches.
- `frontend/src/lib/sse.ts` — accept `after_offset` query param helper.
- `frontend/src/App.tsx` and `ChatPanel.tsx` — re-attach on enter when `turn_state` reports active.

---

## Architecture sketch

### `TurnEntry` (backend `chat/turn_registry.py`)

```python
@dataclass
class TurnEntry:
    turn_id: str
    chat_id: str
    slug: str                       # project slug or _UNBOUND_SLUG
    task: asyncio.Task[None]        # the running chat_turn coroutine
    subscribers: set[asyncio.Queue[str | None]]   # None = sentinel for end
    status: Literal["running", "done", "cancelled", "error"]
    started_at: float
    finished_at: float | None
    last_offset: int                # count of events written to jsonl so far
    error: dict[str, str] | None
```

### `TurnRegistry`

```python
class TurnRegistry:
    """One active turn per chat_id. In-memory only — restart loses live state.
    events.jsonl remains the durable record; on restart, any chat with a
    half-written tail surfaces as 'orphaned' to a reattaching client."""

    def __init__(self) -> None:
        self._by_chat: dict[str, TurnEntry] = {}
        self._by_turn: dict[str, TurnEntry] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        *,
        chat_id: str,
        slug: str,
        runner_factory: Callable[[], AsyncIterator[str]],
    ) -> TurnEntry:
        """Spawn a new turn. Rejects if a turn is already active on chat_id."""

    async def subscribe(
        self, turn_id: str
    ) -> tuple[TurnEntry, asyncio.Queue[str | None]]:
        """Register a subscriber queue. Returns the entry + queue."""

    def unsubscribe(self, entry: TurnEntry, q: asyncio.Queue[str | None]) -> None:
        """Drop subscriber. Idempotent."""

    async def cancel(self, turn_id: str) -> None:
        """Cancel the running task. Idempotent."""

    def get_active_for_chat(self, chat_id: str) -> TurnEntry | None:
        """For reattach: 'is there a turn we should resume tailing?'"""
```

Wrapper around `chat_turn`:
```python
async def _wrap(entry: TurnEntry, runner: AsyncIterator[str]) -> None:
    try:
        async for chunk in runner:
            entry.last_offset += 1
            for q in list(entry.subscribers):
                q.put_nowait(chunk)
        entry.status = "done"
    except asyncio.CancelledError:
        entry.status = "cancelled"
        raise
    except Exception as e:  # noqa: BLE001
        entry.status = "error"
        entry.error = {"error_code": "turn_failed", "error_message_en": str(e)}
    finally:
        entry.finished_at = time.time()
        for q in list(entry.subscribers):
            q.put_nowait(None)   # sentinel: stream ends
```

### Routes (`backend/app/api/routes/turns.py`)

```
POST   /lab/chats/{cid}/turns           body=StartTurnBody → {turn_id, status}
GET    /lab/chats/{cid}/turns/{tid}/stream?after_offset=N → SSE
POST   /lab/chats/{cid}/turns/{tid}/cancel  → {status}
GET    /lab/chats/{cid}/turn_state      → {active_turn_id, status, last_offset} | {active_turn_id: null}
```

`StartTurnBody` is the union of today's `ChatBody` and `UnboundTurnBody`:
- `slug` (required; either a real slug, `_chats` for unbound, or `p_unset`
  for the legacy auto-mint path).
- `user_message`, `attachments`, `surface_context` — unchanged.

Stream endpoint replay logic:
```python
async def stream(cid: str, tid: str, after_offset: int = 0):
    entry = registry.lookup_turn(tid)
    if entry is None:
        # Cold cache — turn already finished and was evicted.
        # Replay from events.jsonl, then close.
        async for chunk in replay_from_disk(cid, after_offset):
            yield chunk
        return
    # Hot path: replay any backlog we missed by reading jsonl up to last_offset,
    # then subscribe.
    if after_offset < entry.last_offset:
        async for chunk in replay_from_disk(cid, after_offset, until=entry.last_offset):
            yield chunk
    entry, q = await registry.subscribe(tid)
    try:
        while True:
            chunk = await q.get()
            if chunk is None: break
            yield chunk
    finally:
        registry.unsubscribe(entry, q)
```

### Frontend store (`stores/chat.ts`)

Slice shape change:
```ts
interface ChatSlice {
  // ...existing
  inflightTurnId: string | null   // per chat_id, persisted in localStorage
  streamAbort: AbortController | null   // controls SSE only, not the turn
}
```

Lifecycle methods (`enterProject`, `switchChat`, `enterUnboundChat`,
`newChat`, `deselect`) call a shared `_detachStream()` helper:
- Aborts `streamAbort` (closes the GET stream connection).
- Does NOT touch `inflightTurnId` (the OLD chat's slice keeps it so the
  user can come back).
- Does NOT POST cancel.

On `enterProject`/`enterUnboundChat`/`switchChat` (after hydrate), check
`localStorage[turn:{cid}]` for `inflightTurnId`:
- If set, `GET /lab/chats/{cid}/turn_state`.
- If `active_turn_id` matches, call `attachStream(cid, tid, after_offset=last_local_offset)`.
- If status is `done`/`cancelled`/`error` (or 404), clear the local
  `inflightTurnId` and rely on jsonl hydrate.

Stop button:
- `cancel()` now does `cancelTurn(cid, tid)` (server-side POST), which
  cancels the asyncio task; the running stream receives `turn_end` /
  error envelope and closes naturally.

---

## Tasks

### T0 — ROADMAP entry + INSIGHTS placeholder

**Files:** `docs/superpowers/plans/ROADMAP.md`, `docs/superpowers/INSIGHTS.md`

Add ROADMAP row at the top of the status table:

```
| **M11** — turn as first-class (decouple SSE from turn lifetime; multi-client attach; "switch view doesn't kill the agent") | `2026-05-19-turn-as-resource.md` | 🚧 in progress | — |
```

Add this plan to the "What each milestone delivers" section (one-paragraph
summary mirroring the table row).

Add INSIGHTS placeholder section #N: "Turn lifetime ≠ SSE lifetime — why
`enterProject` doesn't `abort()` the in-flight stream anymore". Fill the
body in T8 closeout after live verification.

**Test:** none (docs only).

**Commit:** `docs(m11): roadmap row + insights placeholder for turn-as-resource`

---

### T1 — `TurnRegistry` (backend, no routes yet)

**Files:** `backend/app/chat/turn_registry.py`, `backend/tests/unit/test_turn_registry.py`

Implement `TurnRegistry`, `TurnEntry`, `TurnStatus` per the sketch above.
Pure unit — no FastAPI / HTTP. Runner is an `AsyncIterator[str]`; the
registry doesn't know it's chat_turn.

Tests:
- `test_start_and_subscribe_basic` — start a fake runner that yields 3
  chunks; subscriber receives all 3 + sentinel.
- `test_two_subscribers_get_same_stream` — both queues see the same chunks.
- `test_late_subscriber_misses_old_chunks` — registry doesn't buffer old
  chunks; route layer will replay from jsonl. Document this contract.
- `test_cancel_propagates` — `cancel(tid)` flips status to `cancelled`,
  subscribers receive sentinel.
- `test_one_turn_per_chat` — `start` on a chat with an active turn raises
  `TurnAlreadyActiveError`.
- `test_runner_exception` — runner raising sets `status=error` and stores
  the envelope.

**Test:** `cd backend && uv run pytest tests/unit/test_turn_registry.py -v`

**Commit:** `feat(m11-t1): TurnRegistry — in-memory turn lifecycle, multi-subscriber broadcast`

---

### T2 — Routes (`/lab/chats/{cid}/turns*`)

**Files:** `backend/app/api/routes/turns.py`, `backend/app/api/routes/__init__.py`, `backend/app/chat/service.py` (small)

Wire the four new routes. `start_turn` route hands `ChatService.chat_turn(...)`
to `registry.start(runner_factory=lambda: svc.chat_turn(...))`.

Replay helper:
```python
async def replay_from_disk(cid: str, after: int, until: int | None = None) -> AsyncIterator[str]:
    """Read events.jsonl, skip first `after` lines, yield each as an SSE chunk."""
```
Reuse the existing event → SSE formatting from `chat.py:lab_chat` so the
shape on the wire is identical between live and replay.

Cancel route hits `registry.cancel(tid)`; if the turn is unknown, return
`{status: 'not_found'}` (idempotent client behaviour).

Turn-state route reads `registry.get_active_for_chat(cid)`. If none, also
peek `events.jsonl` length for `last_offset` so a reload can hydrate
without first attaching.

**Test:** `cd backend && uv run pytest tests/integration/test_chat_turns_lifecycle.py -v`

Integration tests (new file):
- `test_start_then_stream_full_turn` — POST start, GET stream, see
  `turn_end`, status flips to `done`.
- `test_detach_and_reattach` — start, stream a few chunks, drop the
  connection, query `turn_state`, GET stream with `after_offset` =
  client's last received line; see remaining chunks + `turn_end`.
- `test_two_clients_same_turn` — both clients GET stream; both see all
  chunks. Both detach → turn still finishes; jsonl is complete.
- `test_cancel_via_route` — POST cancel mid-stream; subscriber receives a
  terminating envelope (or just SSE close — both acceptable, document
  the choice in the test).
- `test_unbound_path_via_new_route` — POST start with `slug=_chats`,
  verify events land in `_chats/<cid>.jsonl`.
- `test_one_turn_per_chat_rejected` — second POST start on the same chat
  while turn is running → 409.

**Commit:** `feat(m11-t2): /lab/chats/{cid}/turns* routes — POST start, GET stream, POST cancel, GET state`

---

### T3 — Backwards-compat shim on old routes

**Files:** `backend/app/api/routes/chat.py`

`POST /lab/chat` and `POST /lab/chats/{cid}/turn` keep working: each
delegates to "start a turn, then immediately stream it" so older frontend
builds and any external scripts don't break overnight. Mark with a
deprecation header (`Sunset: ...`) and add a backend log line.

This is a small, defensive layer — no new behaviour, just routing.

**Test:** existing tests for `/lab/chat` still pass.
`cd backend && uv run pytest tests/integration/test_chat_routes.py tests/integration/test_chat_routes_unbound.py -v`

**Commit:** `feat(m11-t3): keep /lab/chat shims alive — delegate to new turn routes`

---

### T4 — Frontend lib: `turn.ts`

**Files:** `frontend/src/lib/turn.ts`, `frontend/src/lib/sse.ts`

```ts
export interface StartTurnBody { /* mirrors backend */ }
export interface TurnState {
  active_turn_id: string | null
  status: 'running' | 'done' | 'cancelled' | 'error' | null
  last_offset: number
}

export async function startTurn(cid: string, body: StartTurnBody): Promise<{ turn_id: string }>
export function attachStream(cid: string, tid: string, opts: { after_offset: number; signal: AbortSignal }): AsyncIterable<{ event: string; data: unknown }>
export async function cancelTurn(cid: string, tid: string): Promise<void>
export async function fetchTurnState(cid: string): Promise<TurnState>
```

`attachStream` is a thin wrapper over `streamSSE` with the `after_offset`
query param baked in.

**Test:** no dedicated unit test for the lib (it's a transport wrapper);
T5 store tests exercise it end-to-end against a mock fetch.

**Commit:** `feat(m11-t4): frontend turn.ts — startTurn / attachStream / cancelTurn / fetchTurnState`

---

### T5 — Frontend store: split `send`, lifecycle methods detach not abort

**Files:** `frontend/src/stores/chat.ts`, `frontend/src/stores/chat.test.ts` (new)

Refactor:
- Add `inflightTurnId: string | null` to slice; persist per-chat in
  localStorage under `turn:{cid}`.
- Rename `abort` → `streamAbort` semantically (still an AbortController,
  but now it only kills the SSE GET, never the backend task).
- `send()` becomes: `startTurn(cid, body) → tid; setInflightTurnId(cid, tid); attachStream(cid, tid, after=events.length)`.
- New `_detachStream()` helper called by `enterProject` (non-adopt branch),
  `switchChat`, `enterUnboundChat` (non-adopt branch), `newChat`,
  `deselect` (non-keep-unbound branch). Aborts `streamAbort`, does NOT
  POST cancel, does NOT clear `inflightTurnId` from the OLD chat's slice.
- `cancel()` (Stop button) now calls `cancelTurn(cid, inflightTurnId)`.

Store unit tests (Vitest, mocked fetch / EventSource):
- `test_switch_project_mid_turn_does_not_bleed` — start a turn on A,
  midway switch to B, push more chunks to A's mock stream, assert B's
  `events[]` only contains B's hydrate result.
- `test_reenter_chat_reattaches` — start turn on A, switch to B, switch
  back to A, assert `attachStream` was called with `after_offset` equal
  to events received so far.
- `test_cancel_calls_server` — Stop button hits `POST cancel`.

**Test:**
`cd frontend && npm test -- chat.test`
`cd frontend && npx tsc --noEmit`

**Commit:** `feat(m11-t5): chat store splits send → startTurn + attachStream; lifecycle detaches without aborting`

---

### T6 — Frontend: re-attach on enter

**Files:** `frontend/src/stores/chat.ts` (enterProject, enterUnboundChat,
switchChat — the hydrate-completion branches)

After `getChatEvents` returns and we apply, if `inflightTurnId` is set for
this chat, call `fetchTurnState(cid)`:
- If `active_turn_id` matches: `attachStream(cid, tid, after=events.length)`.
  Set `busy: true`, `streamAbort` to a fresh controller.
- If status is `done`/`cancelled`/`error`: clear `inflightTurnId`; jsonl
  hydrate already has the final state.
- If `active_turn_id !== inflightTurnId`: stale localStorage; clear.

Idempotent and best-effort — a 404 or network error just falls through
to "no live attach, treat as static history".

**Test:** integration smoke (manual or Playwright)
`cd frontend && npx tsc --noEmit`

**Commit:** `feat(m11-t6): re-attach SSE on chat re-enter when turn still running`

---

### T7 — Live dogfood + ChatPanel reverification

**No code changes** unless smoke surfaces a bug. Smoke scenarios on a real
chat:

1. **Switch-and-return**: send a long /improve-style prompt on project A,
   switch to project B mid-stream, do something on B, switch back to A.
   Expected: A's chat continues to stream from where you left off; B was
   untouched.
2. **Reload mid-turn**: send a prompt, hit Cmd-R mid-stream. Expected:
   page reloads, conv hydrates from jsonl, `attachStream` re-attaches,
   streaming continues.
3. **Two tabs same chat**: open the same chat in two tabs, send a prompt
   in tab 1. Expected: tab 2 sees the same stream live.
4. **Stop button**: send, hit Stop. Expected: `POST cancel` reaches
   backend, agent task cancelled, both tabs see the turn end with
   `cancelled` status.
5. **Stick-to-bottom interaction**: while re-attached after a switch,
   stick-to-bottom still tracks the freshly-arriving events (regression
   check on M10.5 work).

If everything green, fill the INSIGHTS section opened in T0 with the
real reason and link to a representative test.

**Commit:** `docs(m11-t7): closeout — live dogfood notes + INSIGHTS entry on turn lifetime`

Update ROADMAP row from `🚧 in progress` to `✅ shipped + dogfooded` with
the commit range.

---

## Hard rules

- **events.jsonl remains the source of truth.** TurnRegistry is operational
  state. Anything not in jsonl is not durable. Don't add registry-only
  fields that a reload would lose.
- **No new schema/skill changes.** This milestone is purely transport.
- **Old routes (`/lab/chat`, `/lab/chats/{cid}/turn`) keep working** for at
  least this milestone. Cutover is "new frontend → new routes"; we don't
  delete the old ones until a follow-up.
- **One turn per chat.** Second start attempt while running → 409. Don't
  build queueing in this milestone.
- **Cancel is explicit and POSTed.** Closing SSE != cancelling a turn.
- **No new write tools** for the agent. The agent still reads/writes via
  the existing tool surface; this milestone touches only the
  human/CLI-facing HTTP layer + the frontend store.

---

## Test plan summary

- Backend unit: `test_turn_registry.py` (T1) — 6 cases.
- Backend integration: `test_chat_turns_lifecycle.py` (T2) — 6 cases.
- Backend regression: existing `test_chat_routes*.py` stay green through T3.
- Frontend unit: `chat.test.ts` (T5) — 3 cases plus `tsc --noEmit`.
- Live smoke: 5 scenarios in T7.

Total estimate for Phase A: 4–6h of focused work, dominated by getting the
registry's asyncio lifecycle right and the frontend re-attach being
idempotent.

---

# Phase B — symmetry fillers (tool ↔ HTTP dual-form completion)

Companion audit 2026-05-19 found 13 tool-only actions without HTTP
counterparts. Each violates the AI-native API symmetry principle: a CLI
agent that goes through HTTP cannot do what the in-session agent can do
through its tool surface. This phase closes those gaps with thin
RESTful endpoints — each new route is ~15–30 lines that body-validates
and delegates to the same module function the tool already wraps.

**Audit summary (verified 2026-05-19):**

| Tool | Current HTTP | Phase B route |
|---|---|---|
| `create_project` | — | `POST /lab/projects` |
| `write_schema` | — (only `accept-candidate`, a related-but-different op) | `POST /lab/projects/{slug}/schema` |
| `switch_active_model` | — (only GETs) | `PUT /lab/projects/{slug}/models/active` |
| `promote_attachment_to_docs` | — | `POST /lab/projects/{slug}/chats/{cid}/attachments/{filename}/promote` |
| `freeze_version` | — | `POST /lab/projects/{slug}/versions/freeze` |
| `issue_api_key` | — (only `GET /lab/keys/meta`) | `POST /lab/keys` |
| `extract_one` | — (only `/v1/extract` prod fast-path) | `POST /lab/projects/{slug}/extract` |
| `extract_batch` | — | `POST /lab/projects/{slug}/extract/batch` |
| `derive_schema` | — | `POST /lab/projects/{slug}/schema/derive` |
| `create_experiment` | — | `POST /lab/projects/{slug}/experiments` |
| `run_experiment_eval` | — | `POST /lab/projects/{slug}/experiments/{eid}/eval` |
| `promote_experiment` | — | `POST /lab/projects/{slug}/experiments/{eid}/promote` |
| `readiness_check` | — | `GET /lab/projects/{slug}/readiness` |
| `contract_diff` | — | `GET /lab/projects/{slug}/contract-diff?from=v1&to=v2` |
| `score` | — | `POST /lab/projects/{slug}/score` |

(Note: `accept-candidate` is the reverse asymmetry — HTTP exists, no
tool. That's intentional per current design: it's an autoresearch
internal user-acceptance step, and CLI symmetry is satisfied because a
CLI agent can call the HTTP directly. No action needed.)

**Frontend-only state to migrate:**
- `_writeChatId(slug, chatId)` localStorage (per-project "last active chat"). Phase B replaces this with a stateless model: list chats via `GET /lab/chats/{slug}`, sort by `updated_at`, pick latest. The frontend retains localStorage as a cache hint but no longer as the source of truth, so a CLI client / second device sees the same "latest" without server-side coordination.

**`useChat.interrupted` flag** stays frontend-side: after Phase A, the
backend turn carries its own `status` (running/done/cancelled/error)
retrievable via `GET turn_state`. The frontend's `interrupted` becomes a
derived value (`turn_state.status === 'cancelled'`), no longer a primary
state. The rewind-on-resend flow stays as-is.

---

## Phase B tasks

### T8 — Project create + delete + schema/derive

**Files:** `backend/app/api/routes/projects.py`, `backend/app/api/routes/schema.py`, `backend/tests/integration/test_routes_projects_create.py`, `backend/tests/integration/test_routes_schema_derive.py`

Add:
```
POST /lab/projects           body: {name: str, slug?: str} → {slug, project_id, name}
POST /lab/projects/{slug}/schema         body: SchemaShape → {ok: true}
POST /lab/projects/{slug}/schema/derive  body: {filenames?: list[str], notes?: str} → {fields_proposed: int}
```

Each route delegates to the same module function the tool wraps —
`project_mod.create_project`, `schema_mod.write_schema`,
`schema_mod.derive_schema`. Body validates with the existing pydantic
shapes lifted from the tool input schemas.

**Test:** `cd backend && uv run pytest tests/integration/test_routes_projects_create.py tests/integration/test_routes_schema_derive.py -v`

Smoke: end-to-end CLI flow `POST /lab/projects` → `POST .../schema/derive` → `GET /lab/projects/{slug}/schema` returns the derived fields.

**Commit:** `feat(m11-t8): HTTP setters for create_project / write_schema / derive_schema`

---

### T9 — Active-model setter

**Files:** `backend/app/api/routes/models.py`, `backend/tests/integration/test_routes_models_active_put.py`

Mirror the existing `PUT /lab/projects/{slug}/prompts/active` shape — same
body validation, same OCC/last-writer-wins semantics, same response.

```
PUT /lab/projects/{slug}/models/active   body: {model_id: str, expected_id?: str} → MV
```

**Test:** `cd backend && uv run pytest tests/integration/test_routes_models_active_put.py -v`

**Commit:** `feat(m11-t9): PUT /lab/projects/{slug}/models/active — mirror prompts/active`

---

### T10 — Extract + score + readiness + contract-diff

**Files:** `backend/app/api/routes/extract_lab.py` (new), `backend/app/api/routes/eval.py`, `backend/app/api/routes/publish.py`, `backend/tests/integration/test_routes_extract_lab.py`

```
POST /lab/projects/{slug}/extract        body: {filename: str, prompt_id?: str, model_id?: str} → ExtractResult
POST /lab/projects/{slug}/extract/batch  body: {filenames?: list[str], ...} → {job_id} (or sync result for small batches)
POST /lab/projects/{slug}/score          body: {filenames?: list[str]} → ScoreReport
GET  /lab/projects/{slug}/readiness      → ReadinessChecklist
GET  /lab/projects/{slug}/contract-diff?from=v1&to=v2 → ContractDiff
```

The lab `/extract` route is **distinct** from `/v1/{pid}/extract` (which
is the API-key-gated prod fast-path). Lab path uses session auth (none
in dev; same as the rest of `/lab/*`), runs through the same `extract_one`
codepath the tool already uses.

For `extract/batch`: if `len(filenames) > 8`, return a `job_id` and let
the caller poll `/lab/jobs/{job_id}` — matches existing `start_job` /
async semantics. Small batches return synchronously.

**Test:** `cd backend && uv run pytest tests/integration/test_routes_extract_lab.py -v`

**Commit:** `feat(m11-t10): lab HTTP for extract / score / readiness / contract-diff`

---

### T11 — Freeze version + issue API key + promote-attachment

**Files:** `backend/app/api/routes/publish.py`, `backend/app/api/routes/upload.py`, `backend/tests/integration/test_routes_publish_freeze.py`

```
POST /lab/projects/{slug}/versions/freeze         body: {version_id?: str} → {version_id}
POST /lab/keys                                    body: {project_id: str, version_id?: str} → KeyRevealOnce
POST /lab/projects/{slug}/chats/{cid}/attachments/{filename}/promote → {target_filename: str}
```

`POST /lab/keys` returns the **one-time reveal** payload (plaintext only
in this response; never again). Mirrors what the tool already does on
the SSE stream.

`promote` body has no schema — the filename is in the path; idempotency
follows the tool's existing behaviour (re-promote = no-op + return same
target name).

**Test:** `cd backend && uv run pytest tests/integration/test_routes_publish_freeze.py -v`

**Commit:** `feat(m11-t11): lab HTTP for freeze_version / issue_api_key / promote_attachment`

---

### T12 — Experiments setters (create + eval + promote)

**Files:** `backend/app/api/routes/experiments.py`, `backend/tests/integration/test_routes_experiments_setters.py`

```
POST /lab/projects/{slug}/experiments               body: {name, prompt_id?, model_id?, ...} → Experiment
POST /lab/projects/{slug}/experiments/{eid}/eval    body: {filenames?: list[str]} → ScoreReport
POST /lab/projects/{slug}/experiments/{eid}/promote body: {to: 'active' | 'archived'} → {ok: true}
```

**Test:** `cd backend && uv run pytest tests/integration/test_routes_experiments_setters.py -v`

**Commit:** `feat(m11-t12): lab HTTP setters for experiments — create / eval / promote`

---

### T13 — Active-chat-per-project off localStorage

**Files:** `frontend/src/stores/chat.ts`, `frontend/src/stores/projects.ts`

Replace `_writeChatId` / `chatIdFor` / `localStorage.getItem('emerge.activeChatId.<slug>')` with a stateless derivation:

- `enterProject(slug)` flow: hydrate via `GET /lab/chats/{slug}` (existing route) → pick the chat with greatest `updated_at` → set as active. If the list is empty, mint a fresh chatId locally (same as today's `newChatId()`).
- Keep localStorage as an optional cache to avoid one round-trip on cold reload (`if (cached && chats.find(c => c.chat_id === cached)) use cached; else use latest`). The cache is a hint, not authoritative.

Net effect: a second device / a CLI client opens the same project and lands on the same "current" chat without any cross-device sync mechanism. localStorage stops being load-bearing.

**Test:** `cd frontend && npm test -- chat.test && npx tsc --noEmit`

**Commit:** `feat(m11-t13): drop localStorage as authoritative active-chat; use chat list updated_at`

---

### T14 — Closeout: symmetry table + docs update

**Files:** `docs/superpowers/INSIGHTS.md`, `docs/superpowers/plans/ROADMAP.md`, `CLAUDE.md` (small)

Update INSIGHTS with a "tool ↔ HTTP dual-form: complete after M11" entry; link the table in this plan as the canonical reference.

Update CLAUDE.md's "Engineering" section: drop the implicit assumption that some tools are lab-internal-only; explicitly state "every `@tool` registration must ship with a corresponding HTTP route, enforced by `test_symmetry_invariant.py` (new)".

Add `backend/tests/unit/test_symmetry_invariant.py`: enumerate all `@tool` registrations (using the same module-loading path as the SDK), filter out `ui_*` and `ask_user`, then assert each has a matching HTTP route in the FastAPI app. Fails loudly if someone adds a new tool without HTTP.

**Test:** `cd backend && uv run pytest tests/unit/test_symmetry_invariant.py -v`

**Commit:** `feat(m11-t14): symmetry invariant test + docs closeout for tool↔HTTP dual-form`

---

## Phase B test plan

- Per-task integration tests (T8–T12): ~3 cases each, exercising the happy path + one validation failure.
- T13 frontend: existing chat.test.ts plus a new "list chats → pick latest" assertion.
- T14 invariant: single test that locks in the contract going forward.

**Total Phase B estimate:** 6–10h across T8–T14, parallelisable (different files for each tool family). T14's invariant test prevents regression and pays for itself the first time someone adds a tool.

---

## Combined sequencing recommendation

Phase A (T0–T7) lands first because it fixes a live bleed bug and is the
prerequisite for the rest of the symmetry story (turn-state HTTP is part
of Phase A). Phase B (T8–T14) then closes the remaining gaps in any
order — each task is independent at the file level.

If time-boxed: ship Phase A in one commit chain, dogfood for a day, then
start Phase B. Each Phase B task is small enough to land in a single PR.

