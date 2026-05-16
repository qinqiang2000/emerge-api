# Progressive doc vision — agent pulls what it needs, system pushes nothing

> Pull > push. The agent already knows the user is looking at `02270e9a.png`
> (filename is in `## Surface context`); when a question actually needs the
> pixels, the agent calls a tool to fetch them. We do NOT auto-attach the
> current doc to every review-mode turn — that would inflate token cost on
> the 90% of messages that are pure text feedback.

## Background — the bug + the principle

Dogfood, 2026-05-16, in the review overlay's compact chat column:

```
user · 这是什么文档？
agent · 这个文档还没有被提取过（无预测结果）。由于它是 PNG 图片，
       我无法直接预览，但可以帮你跑一次提取来看看内容 ——
       要提取一下这张图吗？
user · 你需要提取才能回答吗，不能多模态 直接来回答
agent · 抱歉，你说得对 […]
       docs/ 里的文件我只能通过提取（调用 LLM）来"读"内容，或者
       你把图片重新粘贴到对话框里，我就能直接看了。
```

Diagnosis (`backend/app/chat/service.py:56` — `_load_image_blocks`):

- Image blocks are only inlined from `attachments[]` (chat-paste / drop)
- `surface_context` carries `filename`, `field`, `page` — but no pixels
- `_load_image_blocks` already supports `source: 'docs'`, but the chat-turn
  caller never composes a `docs/` attachment from `surface_context`

**Reject the obvious fix (push):** "if `surface_context.surface === 'review'`
then auto-inject `docs/<filename>` (or the current PDF page) as a hidden image
block." It works, but every review turn — including pure-text questions like
"这字段啥意思" — pays one image worth of tokens.

**Adopt instead (pull):** surface_context tells the agent which doc the user
sees; a new `read_doc_image(slug, filename, page=1)` tool returns an image
content block on demand. The agent decides per-turn whether to fetch. Cost is
paid only when vision is actually needed.

This generalises beyond review:

- Autoresearch could read a problematic doc's pixels mid-iteration without
  re-extracting
- The publish-stage agent could double-check a counterexample visually
  before promoting
- A chat user asking about a `docs/` file by name ("有什么看法 about
  invoice-3.pdf") gets a visual answer without re-pasting

Same shape as `get_surface_state` (M9.3) and `pdf_render_page` (M1) — both
pre-existing pull-mode pointers the agent already has. This plan adds the
third leg: the actual visual payload.

## Survey of other push hotspots (verified clean)

Grepped `backend/app/chat/service.py` and the system-prompt assembly path
for anywhere we silently bulk-inject state into a turn. Findings:

| Surface | Behaviour | Verdict |
|---|---|---|
| `_build_active_context` | small metadata: slug, active prompt id, active model id, extract_model name | ✅ pointer-only |
| `_build_surface_context_block` | small metadata: filename, field, current_value (short repr), page, page_count, entity_count, experiment_id | ✅ pointer-only; `current_value` is a `repr()`-truncated short string by design |
| `emerge_extractor.md` / `_autoresearch.md` / `_publish.md` | static skill text, no per-turn variables | ✅ |
| `_load_image_blocks` for `source: 'chat'` | only fires when user attaches a file in *this* turn | ✅ user-initiated, equivalent to a paste |
| `_load_image_blocks` for `source: 'docs'` | only fires when chat events carry a docs-source attachment (post-`promote_attachment_to_docs` reference) | ✅ ref persisted across turns is fine; payload is paid once per re-mention |
| Extract LLM path (`provider/*.py` direct) | bulk-injects schema + doc into provider call | ✅ legitimate — that's literally the job |

**Nothing else to change.** The codebase already follows pull. This plan
fills the one missing pull tool.

## What ships

1. `read_doc_image` tool — backend, MCP-registered, returns image content block
2. `emerge_extractor.md` — one-paragraph hint in the review-driving section
3. Hard rule audit — add a one-line bullet to CLAUDE.md "Hard rules"
   reaffirming the pull principle (so the next person reading the file
   knows not to add `auto-attach surface doc to every turn` as a "small UX fix")

## Tasks

### T1 — `read_doc_image` tool function

**Location:** `backend/app/tools/docs.py` (extend existing module).

**Signature:**

```python
async def read_doc_image(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    page: int = 1,
) -> dict[str, Any]:
    """Return the doc's bytes as a base64 image dict for MCP tool-result content.

    - PNG/JPG → read `docs/<filename>` directly, ignore `page` (single-page).
    - PDF → render via existing `pdf_render_page(slug, filename, page)`, returns
      the cached PNG path; read those bytes.
    - Other extensions: raise `ValueError`.

    Returned dict:
        {"data": "<base64>", "mime": "image/png"|"image/jpeg",
         "filename": ..., "page": 1, "page_count": N}

    The MCP wrapper turns this into a `{type: "image", ...}` content block
    that Anthropic's API sees as inline vision."""
```

PDF page-count comes from the sidecar (`docs/.meta/<filename>.json` already
carries `page_count`). For PNG/JPG `page_count == 1`.

Tests (`backend/tests/unit/test_tools_docs.py` — extend):
- PNG round-trip: bytes match `base64.b64encode(file_bytes).decode()`
- JPG round-trip; mime is `image/jpeg`
- PDF page=1 hits `pdf_render_page` cache (assert cache file exists after call)
- PDF page=N out-of-range surfaces the same `ValueError` as `pdf_render_page`
- Unsupported extension (e.g. `.heic` snuck through somehow) raises
- Missing filename raises (mirrors `read_doc`'s OSError behaviour)

### T2 — MCP registration

**Location:** `backend/app/tools/__init__.py`.

Add a `@tool` wrapper near `pdf_render_page` (kindred):

```python
@tool(
    "read_doc_image",
    "Return the visual content of one doc as an inline image so you can see "
    "what the user sees. Use this when the user asks about the visual content "
    "of a doc you can't read from JSON state alone (e.g. 'what is this doc', "
    "'识别一下', 'is this page blurry'). PNG/JPG: pass page=1 (ignored). "
    "PDF: pass the specific page; check surface_context.page if the user is "
    "in review mode. Do NOT call extract just to 'see' a doc — that uses an "
    "LLM call to produce structured JSON; this tool gives you direct vision. "
    "If you need multiple pages of a long PDF, call this tool once per page.",
    {"slug": str, "filename": str, "page": int},
)
async def t_read_doc_image(args: dict[str, Any]) -> dict[str, Any]:
    out = await docs_mod.read_doc_image(
        workspace, args["slug"], args["filename"],
        page=int(args.get("page") or 1),
    )
    return {"content": [
        {"type": "image", "data": out["data"], "mimeType": out["mime"]},
        {"type": "text", "text": _json.dumps({
            "filename": out["filename"], "page": out["page"],
            "page_count": out["page_count"],
        })},
    ]}
```

Verified the SDK supports `{type: "image", data, mimeType}` in tool results
(`claude_agent_sdk/__init__.py:473` — `item_type == "image"` branch wraps
into `ImageContent`).

Test (`backend/tests/unit/test_mcp_registration.py` or wherever the existing
"all tool names registered" test lives): assert `read_doc_image` is in the
MCP server's tool list.

### T3 — Skill copy

**Location:** `backend/app/skills/emerge_extractor.md`.

In the "## Driving the review UI" section, after the four `ui_*` tools and
`get_surface_state`, add:

```markdown
- `read_doc_image(slug, filename, page)` — pull the visual content of one
  doc as an inline image. Use when the user asks about visible content
  ("这是什么文档", "这张图里写的啥", "is the receipt blurry") and the
  surface_context filename + JSON state from `get_surface_state` aren't
  enough. PDF: pass `surface_context.page`; PNG/JPG: page=1.

  **Pull, not push.** We do NOT auto-attach the current doc to every
  review turn — vision tokens are only paid when you call this tool. If
  the question is about labels, descriptions, or schema state, answer
  from JSON tools (`read_schema`, `get_prediction`, `get_reviewed`,
  `get_surface_state`) without calling this one.
```

Also add a one-line clarification in the "## Attachments vs. sample docs"
section so the agent doesn't get confused when a `docs/` file isn't a
recent chat attachment:

```markdown
- For `docs/` files that the user references but did NOT just paste:
  the file is NOT in the current turn's image blocks. To see it, call
  `read_doc_image(slug, filename, page)` — do not ask the user to
  re-paste.
```

### T4 — Hard-rule entry

**Location:** `CLAUDE.md`, under "## Hard rules (red lines)".

Add one bullet:

```markdown
- **Doc vision is pulled, not pushed**. The current review doc is referenced
  via `surface_context.filename` (a pointer) — the bytes are never
  auto-inlined into a chat turn. The agent calls `read_doc_image(slug,
  filename, page)` when (and only when) the question requires vision. Do
  NOT add an "auto-attach current doc" branch to `_load_image_blocks` —
  it inflates token cost on the majority of review turns that are pure
  text feedback.
```

This is the "next-person guard" — without it someone will read the dogfood
transcript and "fix" it by inlining.

### T5 — Live verify

After T1–T4, repro the original transcript:

1. Open `02270e9a.png` (or any review doc) in review mode
2. Chat column → "这是什么文档？"
3. Expect: agent calls `read_doc_image(slug, "02270e9a.png", 1)`, then
   answers based on what's actually visible

If the agent still asks to extract first, the skill copy didn't land — fix
the wording in T3, don't fall back to push.

Then 反向 verify (no over-fire):

1. Open the same doc
2. Chat column → "这个 field 是什么意思" (with a field selected)
3. Expect: agent answers from schema / surface_context, does NOT call
   `read_doc_image` (no vision needed for a description question)

Capture both flows to `chats/<chat_id>.jsonl` for the closeout.

### T6 — ROADMAP closeout

Append a row to `docs/superpowers/plans/ROADMAP.md`:

```
| **2026-05-16** — progressive doc vision (pull-mode `read_doc_image` tool) | `2026-05-16-progressive-doc-vision.md` | 🚧 in progress | — |
```

Move to ✅ + commit range after live verify lands.

## Out of scope

- **Auto-attach on push** — explicitly rejected; T4 enshrines the reason.
- **Frontend changes** — none. The agent returns text; SSE streams it; the
  chat column renders it. The image block is in the agent's *input* not its
  output, so the UI never sees it.
- **Multi-page PDF prefetch** — agent calls `read_doc_image` per page on
  demand. If a user routinely asks 5-page questions, fix it then with
  a `range` parameter; YAGNI now.
- **`read_doc_image` from the public `/v1/{pid}/extract` route** — fast-path
  is text-out only; vision is lab-side.
- **Caching the base64 payload** — `pdf_render_page` already caches the PNG
  on disk; encoding to base64 each call is ~one Python loop over a 50–500 KB
  buffer, faster than the LLM round-trip. Add a memcache if profiling proves
  it.
- **Per-tool retry** — same shape as M5 follow-up; not this plan.

## Decisions affirmed

- **One new tool, no new endpoint.** Lab-only; agent-side. AI-native API
  symmetry intentionally doesn't apply here — the public `/v1` API is
  text-out only, and "let an external script peek at a doc image via API
  key" isn't a use case anyone has asked for. Re-evaluate if it surfaces.
- **Page is a parameter, not "current page" magic.** The agent reads page
  from `surface_context.page` when it has one; passes it explicitly. Tool
  has no implicit dependence on which surface called it.
- **The text block alongside the image** carries `{filename, page,
  page_count}` so the agent can keep its bookkeeping straight when juggling
  multiple `read_doc_image` calls in one turn.

## Risk gates / red lines

- ✅ Agent brain / extract LLM separation: `read_doc_image` is pure file IO
  + base64 — never re-enters the SDK.
- ✅ No bbox / coordinate metadata.
- ✅ Doesn't touch `schema.json` or `versions/`.
- ✅ Task-type-agnostic — works for any doc-extraction-shaped project; for
  non-doc projects (matching, classification) the tool just isn't called.

## Test footprint

- Backend: +6 unit tests (T1 cases) + 1 registration assertion (T2).
- No frontend tests (no UI change).
- One live dogfood walk (T5, two transcripts).
