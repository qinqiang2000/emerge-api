# emerge — Agent-Native Document API Platform

> **Slogan**: Documents in. APIs emerge. They get better as you correct them.
> **Status**: design (2026-05-08)
>
> emerge is a Software 3.0 document API platform. The user drops documents into a project, talks to an agent, corrects what's wrong, and gets a stable extraction API. Lab side is chat-driven via `claude_agent_sdk`; the published API is a deterministic fast-path that never invokes the agent.

---

## 0. Motivation

Document extraction tools sit in a strange middle: they want to be developer products (predictable APIs) but their core labour is judgement (which value is correct?). v1 thinking treated this as a CRUD application with an annotation UI bolted on. The result was workflow ceremony — wizards, forms, modals — burying the AI-native shape that should have been front-and-centre.

emerge inverts the surface:

- **Chat is the primary interface.** The agent owns orchestration.
- **Every meaningful action is a tool.** Tools are atomic, auditable, side-effecting on the filesystem.
- **Every artefact is a file.** A project is a folder. The user can `ls`, `cat`, `git diff`, `scp`. There is no database.
- **Description-as-code.** The user's creative labour is writing each field's natural-language description. AutoResearch evolves those descriptions; nothing else is a knowledge channel into the model.

The product slogan applies twice: documents in → an extraction API emerges; corrections in → that API gets better.

---

## Glossary

| Term | Meaning |
|---|---|
| **Project** | A working unit publishing one extraction API. Lives entirely under `workspace/{project_id}/`. v1 implements `project_type=extraction` only. |
| **Document** | An uploaded PDF or image, content-addressed by sha256. |
| **Schema** | The list of fields the API extracts, each with a natural-language `description`. The single source of truth lives in `schema.json`. |
| **Reviewed example** | A user-confirmed extraction result for a specific document. Ground truth for evaluation; never enters the runtime prompt. |
| **Counterexample / regression case** | A `(doc, wrong_output, correct_output)` triplet from production feedback. Used by AutoResearch's regression test only; never enters the runtime prompt. |
| **Agent brain** | The Claude model running inside `claude_agent_sdk.ClaudeSDKClient` that drives the chat. Stateless across turns; all context is recovered from the filesystem. |
| **Skill** | A `SKILL.md` loaded into the agent's context that carries domain *discipline* (red lines, output contracts, when-to-stop rules). emerge has 3. |
| **Tool** | A Python `@tool` async function exposed to the agent through the SDK's MCP integration. Atomic and deterministic where possible. |
| **Three-layer LLM** | Three independent model configurations: (1) Agent brain via SDK, (2) Extract LLM via direct provider HTTP per project, (3) AutoResearch proposer via direct provider HTTP. |
| **Compiled fast path** | The `/v1/{pid}/extract` HTTP endpoint that loads a frozen `versions/v{n}.json` and calls the provider directly. Never enters the agent loop. |
| **Evidence trace** | `_source_page` integers (one per field) emitted alongside extraction output, enabling click-to-page in review without storing coordinates. |

---

## 1. Conceptual model

### 1.1 The user's mental model

> A project is a folder. I drop documents in. I tell the agent what I want. The agent builds a schema, runs extractions, asks me to review a few. I correct what's wrong. I run eval. If the score isn't enough, I say `/improve` and the agent optimizes the field descriptions while I do other things. When I'm happy, I say `/publish` and get an API key.

Everything in that paragraph maps 1:1 to a tool call. Nothing is hidden behind a database. The artefacts the user creates are the artefacts the system uses.

### 1.2 The agent's mental model

> I have three skills (extractor, autoresearch, publish) that carry the discipline I must respect. I have ~17 tools that touch the filesystem and call LLMs. The user's project state is whatever files currently exist under `workspace/{pid}/`. I never persist state in my own memory — at the start of every turn I read what I need.

### 1.3 Three-layer LLM separation

| Layer | Driver | Provider lock-in | Configured at |
|---|---|---|---|
| **Agent brain** | `claude_agent_sdk` | Anthropic (Sonnet 4.6 / Opus) | system env / global config |
| **Extract LLM** | direct provider HTTP | none (Anthropic / OpenAI / Gemini …) | `project.json` per project |
| **Proposer LLM** (autoresearch) | direct provider HTTP | none | system default + per-job override |

Agent brain **must not** reach Extract LLM through the SDK. LLM-in-LLM recursion would explode cost and break determinism. The provider adapter is a separate module from the SDK integration — they share nothing but the JSON output contract.

### 1.4 Description-as-code

The only knowledge channel into the extraction model is `schema.fields[].description` and `global_notes.md`. There is no image few-shot anywhere. There are no example I/O pairs injected. To teach the model a rule, the user (or AutoResearch on their behalf) writes that rule in plain language into a description field.

This makes all teaching legible. There is no hidden knowledge baked into examples that nobody re-reads.

---

## 2. Architecture overview

```
┌──────────────────── Frontend (Vite + React 19 + Tailwind v3) ──────┐
│                                                                    │
│  ┌───────────┐  ┌──────────────────────────┐  ┌────────────────┐   │
│  │ Projects  │  │      Chat (SSE)          │  │  Right pane    │   │
│  │           │  │  user / agent turns      │  │  (toggle)      │   │
│  │           │  │  slash menu              │  │  📄 doc        │   │
│  │           │  │  drag-drop docs          │  │  📊 metrics    │   │
│  └───────────┘  └──────────────────────────┘  └────────────────┘   │
│                                                                    │
│  Review mode = full-canvas takeover:                               │
│    PDF (60%) | JSON edit + inline comment + chips/stepper (40%)    │
│    chat docks bottom-right corner                                  │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ HTTP + SSE
┌──────────────────────────────▼─────────────────────────────────────┐
│  Lab API (FastAPI)  ── /lab/chat /lab/upload /lab/jobs              │
│                                                                    │
│   ChatService  ── claude_agent_sdk.ClaudeSDKClient                 │
│                   + ClaudeAgentOptions(mcp_servers=emerge_tools)   │
│   JobRunner    ── asyncio queue for /improve, extract_batch        │
│                                                                    │
│            Skills (SKILL.md):                                      │
│              emerge-extractor  (always loaded)                     │
│              emerge-autoresearch (loaded for /improve)             │
│              emerge-publish     (loaded for /publish)              │
│                                                                    │
│            Tools (Python @tool, registered as MCP):                │
│              ~17 atomic functions, see §5                          │
│                                                                    │
│            Provider adapter (separate module, no SDK dep):         │
│              provider/{anthropic,openai,gemini}.py                 │
│              shared by extract / derive_schema / proposer / prod   │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ filesystem only
┌──────────────────────────────▼─────────────────────────────────────┐
│  workspace/                                                        │
│    _keys.json                # api key hash → project (no DB)      │
│    _job_locks/               # workspace-wide flock files          │
│    {project_id}/             # one project = one folder            │
│      project.json                                                  │
│      schema.json                                                   │
│      global_notes.md                                               │
│      docs/{doc_id}.{pdf|png|jpg}                                   │
│      reviewed/{doc_id}.json                                        │
│      predictions/_draft/{doc_id}.json                              │
│      versions/v{n}.json      # frozen, immutable                   │
│      versions/_candidate/{job_id}/turn_{k}.json                    │
│      metrics/eval_{ts}.json                                        │
│      jobs/{job_id}.jsonl     # autoresearch progress events        │
│      chats/{chat_id}.jsonl   # conversation log incl. tool calls   │
│      .lock                   # flock target for mutating writes    │
└────────────────────────────────────────────────────────────────────┘

┌──────────────────── Prod API (separate FastAPI router, no agent) ──┐
│  POST /v1/{project_id}/extract  →  load versions/v{active}.json    │
│                                  →  build prompt, call provider    │
│                                  →  return JSON (strip _evidence   │
│                                       unless project opts in)      │
│  Auth: per-project API key from workspace/_keys.json               │
└────────────────────────────────────────────────────────────────────┘
```

---

## 3. Filesystem layout

### 3.1 Workspace root

```
workspace/
├── _keys.json          # { ek_xxx_hash: { project_id, scope: "extract", created_at, last_used } }
├── _job_locks/         # workspace-wide transient flock files (cleaned on startup)
└── {project_id}/       # project folder
```

`_keys.json` is loaded into memory at startup and reloaded on atomic-rename change. Lookups in the `/v1/{pid}/extract` hot path are in-memory.

### 3.2 Project folder

```
{project_id}/
├── project.json               # { name, project_type, created_at, extract_model, extract_params,
│                                  autoresearch_proposer_model, active_version_id }
├── schema.json                # current editing-state schema (lab truth)
├── global_notes.md            # free-text cross-field hints
├── docs/                      # uploaded files, content-addressed by sha256
│   ├── {doc_id}.pdf
│   └── {doc_id}.meta.json     # { filename, page_count, uploaded_at, sha256 }
├── reviewed/{doc_id}.json     # ground truth: { entities, _notes? }
├── predictions/_draft/{doc_id}.json   # latest extract output, overwritten on rerun
├── versions/
│   ├── v{n}.json              # frozen at /publish: { schema, global_notes, model_id, params, frozen_at }
│   └── _candidate/{job_id}/turn_{k}.json   # autoresearch outputs, never auto-promoted
├── metrics/eval_{ts}.json     # { schema_hash, predictions_hash, f1, per_field, errors[] }
├── jobs/{job_id}.jsonl        # per-project autoresearch progress events
├── chats/{chat_id}.jsonl      # conversation log
└── .lock                      # flock target
```

### 3.3 File-handling invariants

| Invariant | Mechanism |
|---|---|
| Single mutating writer per project | `flock(LOCK_EX)` on `{pid}/.lock` |
| Important files never half-written | `tmp/.{name}.tmp` → `fsync` → `os.replace` |
| `versions/v{n}.json` immutable | `chmod 0o444` after write; freeze code path is the only writer |
| `schema.json` not auto-mutated by autoresearch | Candidates always go to `versions/_candidate/`; user-explicit accept copies into `schema.json` |
| Logs survive crash | JSONL append-only; partial trailing line discarded on read |
| `_keys.json` stores hashes only | Plaintext API key exists only in the create-key response and is never written to disk |

---

## 4. Skills

Three skills, sliced by **discipline** (not by verb). Slash commands trigger skill load; free-form chat routes via the default skill.

### 4.1 `emerge-extractor` (default, always loaded)

**Discipline:**
- Description-as-code: the only knowledge channel into the extraction model is `schema.fields[].description` and `global_notes.md`. No image few-shot. No injected example I/O.
- Output contract: top-level `array<object>`, snake_case English keys, omit fields when uncertain (no hallucinated nulls).
- Evidence trace: extractor must emit `_evidence: [{field_name: page_int}]` parallel to `entities`.
- No bbox or coordinate metadata anywhere — page integers only.
- Risk gates: structural schema mutations (add/remove/rename field) require user confirmation; description-text edits do not.

**Owns intents:** `init` · `extract` · `eval` · `review` · `feedback`.

### 4.2 `emerge-autoresearch` (loaded on `/improve`)

**Discipline:**
- Bounded by `max_turn` and `early_stop_no_improvement`. No token / $ budget — lab side is not cost-constrained.
- Each iteration writes a candidate to `versions/_candidate/{job_id}/turn_{k}.json`. Never mutates `schema.json` directly.
- Counterexamples (regression cases) feed only the regression test, never the runtime prompt.
- Job is a background asyncio task; pause / resume / cancel honored.
- Inline `_notes` from reviewed examples are passed to the proposer LLM as user-priority hints.
- On termination: surface candidate diff to user; `schema.json` updates only on explicit accept.

### 4.3 `emerge-publish` (loaded on `/publish`)

**Discipline:**
- Readiness checklist must fully pass before freezing.
- `freeze_version` is atomic; `versions/v{n}.json` is set `0o444` immediately after write.
- Contract diff vs previous published version: added fields allowed; removed / type-changed / enum-narrowed → reject, prompt the user to add a new endpoint instead of overwriting.
- `active_version_id` is single-valued. Editing `schema.json` after publish does not affect prod; only the next `/publish` does.
- API key surfaced one-time in the chat reveal; only the hash is stored in `_keys.json`.

---

## 5. Tools

All tools are async Python functions decorated with `@tool` and registered as MCP via `ClaudeAgentOptions(mcp_servers=...)`. LLM-touching tools call the provider adapter directly; they do not recurse into the SDK.

### 5.1 Project & document
```
create_project(name, project_type='extraction') -> project_id
upload_doc(project_id, bytes, filename) -> doc_id
list_docs(project_id, filter?) -> [{doc_id, filename, page_count, ...}]
read_doc(project_id, doc_id) -> bytes
delete_doc(project_id, doc_id)               # GATED
pdf_render_page(project_id, doc_id, page) -> png_path
update_project(project_id, patch)            # changes extract_model, params, etc.
```

### 5.2 Schema (description-as-code)
```
read_schema(project_id) -> SchemaField[]
write_schema(project_id, schema, reason: str)        # auditable; structural change gated
derive_schema(project_id, sample_doc_ids, intent)    # LLM call via provider
diff_schema(project_id, version_a, version_b)
```

### 5.3 Extraction & evaluation
```
extract_one(project_id, doc_id, schema?, model_id?) -> {entities, _evidence}
extract_batch(project_id, doc_ids, model_id?) -> job_id  # background
score(project_id, predictions_set, reviewed_set) -> {f1, per_field, errors[]}
```

### 5.4 Reviewed examples
```
save_reviewed(project_id, doc_id, json, source: 'manual'|'feedback', notes?)
list_reviewed(project_id) -> [...]
```

### 5.5 Versions & publish
```
freeze_version(project_id) -> version_id            # GATED (only emerge-publish calls)
readiness_check(project_id) -> [{check, pass, detail}]
contract_diff(project_id, candidate_schema, prev_published_schema) -> {added, removed, type_changed, enum_narrowed}
issue_api_key(project_id) -> {key_plaintext, key_hash}      # GATED, one-time reveal
```

### 5.6 Long-running jobs
```
start_job(skill, params) -> job_id
tail_job(job_id) -> SSE stream of events
pause_job(job_id) / resume_job(job_id) / cancel_job(job_id)
```

---

## 6. Routing

### 6.1 Slash commands (context-filtered)

| Command | Available when | Loads skill | Notes |
|---|---|---|---|
| `/new` | always | extractor | creates project, agent prompts for sample docs |
| `/extract` | project selected | extractor | runs over all docs unless user specifies subset |
| `/eval` | project selected, ≥1 reviewed | extractor | |
| `/review` | project selected | extractor | opens review mode on first un-reviewed doc |
| `/improve` | project selected, ≥5 reviewed | autoresearch | minimum 5 chosen so autoresearch has signal beyond noise; tunable |
| `/publish` | project selected, ≥1 eval passes readiness | publish | readiness checklist defined in §4.3 / `readiness_check` tool |
| `/feedback` | project selected | extractor | client-feedback path (e.g. "missing BRN field") |
| `/pause` `/resume` `/cancel` | active job | n/a | direct job control |

### 6.2 Free-form chat routing (no slash)

Default skill is `emerge-extractor`. Per-turn, it decides:
- Apply edit directly (e.g. "改 description 文本" → `write_schema`)
- Delegate to `emerge-autoresearch` (e.g. "开始优化吧" → `start_job(skill='autoresearch')`)
- Delegate to `emerge-publish` (e.g. "发布" → load skill, run readiness)
- Ask a clarifying question (only if intent is genuinely ambiguous)

### 6.3 Risk gates (agent never auto-fires)

| Action | Why gated |
|---|---|
| `freeze_version` + activate | affects public API contract |
| `write_schema` with structural change (add/remove/rename) | cannot be silently rolled back |
| `delete_doc` | irreversible |
| Accept autoresearch candidate → overwrite `schema.json` | discipline red line; user must see diff |
| `cancel_job` | discards work |

Description-text edits are **not** gated. AutoResearch starting via explicit `/improve` is **not** gated (consent implicit).

---

## 7. Data flow traces

### 7.1 case1 — from zero to published API

| Step | User | Agent / tools | Filesystem effect |
|---|---|---|---|
| 1 | drag 20 PDFs + "提取该发票核心信息" | `create_project` → `upload_doc × 20` → `derive_schema(sample=3, intent=...)` → `write_schema` → `extract_batch` | new `{pid}/` with `project.json`, `schema.json` (e.g. 8 fields), `docs/*.pdf × 20`, `predictions/_draft/*.json × 20`, `chats/c_xxx.jsonl` |
| 2 | "把 document_type 改成只允许 invoice/others，规则…" | `write_schema(reason='user edit description')` (description text only, no gate) | `schema.json` updated |
| 3 | `/extract` | `extract_batch` | `predictions/_draft/` overwritten |
| 4 | review 5 docs in review mode | `save_reviewed × 5` | `reviewed/*.json × 5` |
| 5 | `/eval` | `score` | `metrics/eval_{ts}.json`; agent reports F1 |
| 6 | `/improve` | `start_job(skill='autoresearch')`; loop runs `max_turn` or early-stops at `early_stop_no_improvement` | `versions/_candidate/{job_id}/turn_*.json`, `jobs/{job_id}.jsonl`; on accept → `schema.json` overwritten |
| 7 | `/publish` | `readiness_check` → user confirm → `freeze_version` → `issue_api_key` | `versions/v1.json` (immutable), `_keys.json` row, `project.json.active_version_id = "v1"` |

User receives `curl -X POST /v1/{pid}/extract -H "X-API-Key: ek_xxx" -F file=@invoice.pdf`.

### 7.2 case2 — incremental field addition

User reopens `inv-MY` and says: "客户反馈：缺 BRN 字段；BRN 注意只取新格式 12 位数字，括号内旧号忽略".

| Step | Agent / tools | Filesystem effect | Gate |
|---|---|---|---|
| 1 | `read_schema` → propose diff: add `supplier_brn` field with description encoding the new/old number rule → present diff to user | (none until accept) | structural change → **gated** |
| 2 | user accepts → `write_schema` | `schema.json` now 9 fields | |
| 3 | `extract_batch` rerun | `predictions/_draft/*.json` updated; agent flags 5 previously-reviewed docs as "schema changed, please re-review the new field" | |
| 4 | user re-reviews → `save_reviewed × 5` (full JSON including new BRN) | `reviewed/*.json` updated | |
| 5 | `/eval` → `/improve` (if score insufficient) → `/publish` | `versions/v2.json` frozen, `active_version_id = "v2"`, contract diff (additive) passes | publish → **gated** |

API endpoint path unchanged. Same API key. Returned JSON gains `supplier_brn`. Backward-compatible.

---

## 8. UI shell

### 8.1 Default three-pane

```
┌────────┬────────────────────────────────┬────────────────────┐
│Projects│ Chat (SSE)                     │ Right pane (toggle)│
│        │                                │                    │
│● inv-MY│ user: 提取该发票核心信息        │ 📄 doc preview     │
│  20doc │ agent: 已建项目…                │ 📊 metrics         │
│  F1.82 │   [tool: derive_schema] ✓ 8字段│                    │
│  v1▲pub│   [tool: extract_batch] ✓      │                    │
│        │ agent: 15 张一致, 5 张缺…       │                    │
│○ po-CN │                                │                    │
│ + new  │ /  ← slash menu                │                    │
│        │ + drag-drop docs               │                    │
└────────┴────────────────────────────────┴────────────────────┘
```

### 8.2 Review mode (full-canvas takeover)

Clicking "review this doc" from chat or right-pane transforms layout (pattern inspired by Claude Design's expand-artifact flow):

```
┌─[← invoice-001 · 3/20 · prev/next] ────────────────────────────┐
│                                  │ document_type           p.1 │
│                                  │ ● invoice  ○ others         │ ← enum chips
│                                  │                             │
│                                  │ invoice_no              p.1 │
│   Large PDF (60%)                │ [ INV-001                 ] │ ← string input
│                                  │                             │
│   click value in JSON →          │ buyer_name              p.1 │
│   page jumps via _source_page    │ [ ACME Corp               ] │
│   + best-effort text-search      │ 💬 official: ACME Sdn Bhd   │ ← inline comment
│   highlight (no bbox guarantee)  │                             │
│                                  │ total_amount            p.2 │
│                                  │ [ −  1250.50  + ]           │ ← number stepper
│                                  │                             │
│                                  │ [save & next ↩]             │
└──────────────────────────────────┴─────────────────────────────┘
                                              chat docked ●
```

`Esc` or `[← back]` returns to three-pane.

### 8.3 Field controls auto-derived from schema type

| Schema type | Control |
|---|---|
| `enum` | chip group, single-select |
| `number` | stepper (− value +); free type also OK |
| `date` | native date picker + format hint from description |
| `string` | input; large strings → textarea |
| `array<object>` | nested table, add/remove rows |
| `boolean` | toggle |

Controls are React-rendered from `schema.json` client-side — no agent involvement per render.

### 8.4 Inline comments (`_notes`)

Right-click or long-press on any field value in review mode → comment input. Stored in `reviewed/{doc_id}.json`:
```json
{
  "entities": [{ "buyer_name": "ACME Corp", ... }],
  "_notes": { "buyer_name": "official: ACME Sdn Bhd" }
}
```
AutoResearch loads `_notes` from all reviewed examples and feeds them to the proposer LLM as **user high-priority hints** — turning user judgement into structured optimization signal.

### 8.5 Tool-call rendering in chat

Folded by default: `[derive_schema] ✓ 8 fields`. Click expands to params + result. Failed tool calls show red border with `error_code` + retry button.

### 8.6 Visual identity

Anthropic brand palette as the semantic-token base:

```css
/* light */
--bg-canvas:      #faf9f5;
--bg-surface:     #ffffff;
--bg-subtle:      #e8e6dc;
--fg-primary:     #141413;
--fg-secondary:   #6b6a64;
--fg-muted:       #b0aea5;
--accent-primary: #d97757;   /* CTA, brand mark, status ▲pub */
--accent-info:    #6a9bcc;   /* tool-call accent */
--accent-success: #788c5d;   /* pass, F1 up */
--accent-danger:  #b53a2b;   /* error */

/* dark — invert bg/fg, accents unchanged */
```

Typography: **Poppins** for headings, **Lora** for chat body, **JetBrains Mono / ui-monospace** for JSON / code / field names / scores. Lora is reserved for prose; data-dense regions stay mono.

---

## 9. Error handling

### 9.1 Envelope

```json
{ "error_code": "extract_invalid_json", "error_message_en": "Provider returned malformed JSON after 2 attempts" }
```

Frontend localizes by `error_code`. Agent reasons by `error_code` when deciding next action.

### 9.2 Categories

| Category | Examples | Handling |
|---|---|---|
| Tool I/O | file missing, disk full, JSON corrupt | tool returns envelope; agent reacts in chat |
| Provider | rate-limit, timeout, quota | provider adapter retries 3× exponential; on final fail, surfaces `provider_quota` / `provider_timeout` |
| JSON validation | extractor output violates `responseSchema` | 1 retry with stricter system message; final fail → `extract_invalid_json`, batch continues |
| Domain | empty reviewed set, F1 NaN, breaking contract | explicit codes (`no_ground_truth`, `breaking_contract_change`) — never silent success |
| Crash recovery | mid-job process kill | startup scans `_job_locks/` for stale flocks and per-project `jobs/*.jsonl` whose last event is `running` → marks `crashed`; atomic writes mean no half-files; user retries |

---

## 10. Testing

Layered to fit "agent + LLM" reality. Core principle: **never assert "given prompt X, agent calls tool Y"**. LLM behaviour is non-deterministic; such tests would be flaky and brittle.

| Layer | What | LLM | Frequency | Blocks PR? | Approx count |
|---|---|---|---|---|---|
| **Tool unit** | atomic tool functions, mocked provider | none | every commit | yes | ~80 |
| **Provider contract** | adapter behaviour vs each provider, HTTP mocked | none | every commit | yes | ~30 |
| **Skill replay** | record real chat session as JSONL fixture; replay against agent with `StubLLM`; assert filesystem terminal state | stub | every commit | yes | ~15 |
| **LLM smoke** | case1 + case2 happy path end-to-end with cheap real model (haiku 4.5 / gpt-4o-mini) | real | nightly + PR | warn-only | ~3 |
| **Frontend** | vitest components + Playwright e2e (drag-drop, slash, review mode, save) | n/a | every commit | yes | ~50 |

Two independent mock surfaces:
- `StubLLM` mocks the SDK's brain output (skill replay).
- `provider/_test_doubles.py` mocks the provider adapter HTTP layer (tool unit + contract tests).

They never interact.

---

## 11. Implementation phases

### M1 — Walking skeleton (~1.5 weeks)

**Goal**: end-to-end case1 steps 1–3 — drag PDFs + "extract core info" → `derive_schema` → first extract → results streamed back.

- `claude_agent_sdk` chat service
- `emerge-extractor` SKILL.md v1
- Tools: `create_project`, `upload_doc`, `derive_schema`, `write_schema`, `read_schema`, `extract_one`, `extract_batch`, `pdf_render_page`, `list_docs`
- Provider adapter: Anthropic only
- Filesystem layout finalized
- Frontend three-pane shell, chat SSE, drag-drop, tool-call folded cards

**Out of scope for M1**: review mode, eval, improve, publish.

**Acceptance**: drag 5 PDFs + free-form intent → first extraction visible in <10 s.

### M2 — Reviewed examples + Eval + Improve (~2 weeks)

- Tools: `save_reviewed`, `list_reviewed`, `score`
- Review mode (full-canvas takeover) with `_source_page` evidence trace, inline comments, type-derived field controls
- `emerge-autoresearch` SKILL.md + JobRunner (asyncio queue + JSONL event stream + pause/resume/cancel)
- Provider adapter: add OpenAI (verify multi-provider correctness)

**Acceptance**: case1 fully through to "I have F1 0.85 candidate".

### M3 — Publish + case2 (~1 week)

- `emerge-publish` SKILL.md
- Tools: `freeze_version`, `readiness_check`, `contract_diff`, `issue_api_key`
- Prod fast-path `/v1/{pid}/extract` with API-key auth
- API key one-time reveal modal
- case2 entry path

**Acceptance**: case2 end-to-end; curl call against `/v1/{pid}/extract` returns 9-field JSON for v2.

### M4 — Polish (~1 week, can overlap M3 tail)

- Dark mode aligned with brand palette
- Real-LLM smoke CI
- Tool-failure UX in chat (red card, retry, error_code copy)
- Export bundle (`schema.json` + `curl` example + readme)
- Inline comments → autoresearch hint loop verified

Total: **~5.5 weeks single-person**, parallelizable to 2 people after M1.

---

## 12. Hard rules (red lines)

These survive any future refactor without question:

1. **No image few-shot anywhere.** The only knowledge channel into the model is `schema.fields[].description` and `global_notes.md`.
2. **No bbox / coordinate information.** Page integers via `_evidence` are the only spatial metadata.
3. **AutoResearch never auto-promotes.** Output is a candidate; user must explicitly accept.
4. **Counterexamples never enter the runtime prompt.** Regression test set only.
5. **Public API reads `versions/v{active_version_id}.json` only.** `schema.json` is mutable lab state and must not bleed into prod.
6. **No reading or writing `.env` / provider keys / API key plaintext.** Plaintext API key exists only in the one-time reveal response and is never logged.
7. **Agent brain (SDK) and Extract LLM (provider adapter) are separate code paths.** No SDK recursion from inside a tool.
8. **`schema.json` mutated only through `write_schema` tool.** AutoResearch writes to `versions/_candidate/`; user-accept copies forward atomically.

---

## 13. Deferred / future scope

- `MatchingProject` / `VerificationProject` types — same agent + skills + tools shape, distinct skills and tools per type
- Multi-tenant isolation (introduced as outer folder layer `workspace/{tenant}/{project}/` without affecting tools or skills)
- Template marketplace / cross-project schema libraries
- TS types / Postman collection in publish bundle
- Web-capture-from-URL doc ingestion
- Diff-aware autoresearch (using version history as gradient signal)
- AutoResearch advanced stopping criteria (per-field convergence, not just global F1)
- Real-time collaboration in review mode
- Mobile / read-only viewer for stakeholder review

---

## Appendix A — Provider adapter contract

```python
# backend/app/provider/base.py
class Provider(Protocol):
    async def extract(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_content: list[ContentBlock],   # text + image refs
        response_schema: dict,
        params: dict,
    ) -> ProviderResult:
        """Returns raw JSON output. Adapter handles retry/backoff internally."""
```

Implementations: `provider/anthropic.py`, `provider/openai.py`, `provider/gemini.py`. All tested via the same contract suite.

## Appendix B — Skill loader

```python
# Pseudocode — SKILL.md contents loaded into ClaudeAgentOptions.system_prompt
options = ClaudeAgentOptions(
    system_prompt=concat(
        load_skill("emerge-extractor"),                  # always
        load_skill(active_skill) if active_skill else "" # /improve or /publish loads additional
    ),
    mcp_servers={"emerge_tools": emerge_tools_server},
    permissions={"deny": [...standard secrets denylist...]},
)
```

---

*End of design. Implementation plans live under `docs/superpowers/plans/` per milestone.*
