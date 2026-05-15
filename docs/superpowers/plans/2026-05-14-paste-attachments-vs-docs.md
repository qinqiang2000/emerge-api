# Paste-attachments ≠ docs/ samples

## Context

Today, when a user pastes/drops an image in chat:
- **Empty hero** → backend silently mints a project + claims the file into `docs/` (lab/service.py:237-296)
- **In project** → `/lab/projects/{slug}/upload` writes the file straight into `docs/` (with sidecar)

This conflates "conversational scratch" with "curated sample set." `docs/` is the source of truth for AutoResearch eval, predictions, review-mode click-to-page — letting every debug screenshot enter it pollutes eval scores, prediction counts, and review UI. It also violates the digital-colleague mental model: a colleague doesn't auto-file your Slack screenshots into the project drive.

**Rule we want to enforce:** "显式告知才进入样本集." Paste defaults to conversation-scoped attachment; promotion to `docs/` requires an explicit user ack (NL trigger → agent confirms → agent calls promote tool).

Outcome: `docs/` stays curated. The `untitled-260514-152406` style pollution stops. Empty-hero "ask without commitment" works.

---

## Storage model

Add a new conversation-scoped attachment path; leave `docs/` semantics untouched.

| Layer | Path | Lifetime | Sidecar |
|---|---|---|---|
| **Chat-scoped attachment** (NEW) | `workspace/<slug>/chats/<chat_id>/attachments/<filename>` | Until chat deleted | None — ephemeral |
| **Sample doc** (UNCHANGED) | `workspace/<slug>/docs/<filename>` + `docs/.meta/<filename>.json` | Project lifetime; powers eval/predictions | Yes (sha256, page_count, …) |

`chats/<chat_id>/` currently has only `<chat_id>.jsonl` + `<chat_id>.meta.json` (paths.py:102, chat/log.py:23/177) — adding `attachments/` sub-dir is safe.

---

## Backend changes

### 1. New path helpers — `app/workspace/paths.py`
- `chat_attachments_dir(workspace, slug, chat_id) → Path`
- `chat_attachment_path(workspace, slug, chat_id, filename) → Path`

### 2. New staging claim variant — `app/workspace/staging.py`
- Add `claim_staged_to_chat(workspace, token, slug, chat_id) → final_filename` — move `_staging/{token}/<filename>` → `chats/<chat_id>/attachments/<filename>` with dedupe (factor out `_dedupe_filename` from `tools/docs.py:67-82` into a shared helper). No sidecar.
- Keep `claim_staged` (staging.py:134-161) as-is — promote-tool path can still reuse it.

### 3. Rewrite mint block — `app/chat/service.py:236-296`
- On `p_unset + stage_token`: still mint placeholder project (chat persistence requires it), but rename placeholder from `Untitled-{ts}` to `Chat-{ts}` (`_placeholder_project_name` line 112-117) to signal "this is a conversation, not a curated project."
- Replace `claim_staged(..., new_slug)` with `claim_staged_to_chat(..., new_slug, chat_id)` — files land in chat attachments, not docs/.
- `project_minted` SSE payload unchanged (slug + pid + name).

### 4. New endpoint — `app/api/routes/upload.py`
- `POST /lab/projects/{slug}/chats/{chat_id}/attach` (multipart file) → writes to `chat_attachment_path(...)` with dedupe → returns `{filename}`.
- Add `GET /lab/projects/{slug}/chats/{chat_id}/attachments/{filename}` for the frontend to render image thumbnails (`<img src>`). Validate slug + chat_id via existing `safe_slug`.

### 5. Image-block resolver — `app/chat/service.py:53-87 _load_image_blocks`
- Change signature: `_load_image_blocks(workspace, slug, chat_id, attachments)`.
- For each attachment, dispatch on `source`:
  - `source == "chat"` (default for new) → read via `chat_attachment_path(workspace, slug, chat_id, filename)`
  - `source == "docs"` → read via `doc_path(...)` (legacy + post-promote path)
- Update caller around line 344 to pass `chat_id`.

### 6. Persist source on attachments — `app/chat/service.py:302-309`
- `persisted_attachments` now emits `{filename, source}` where source is `"chat"` for paste/drop, `"docs"` for explicit-promote refs.
- For the mint block (line 270): emit `{filename: final_name, source: "chat"}`.
- For in-project paste path: frontend sends `{filename, source: "chat"}` (see frontend changes); pass through.

### 7. New MCP tool — `app/tools/__init__.py` (+ new `app/tools/promote.py`)
- `promote_attachment_to_docs(slug, chat_id, filename) → {final_name}`
  - Read bytes from `chat_attachment_path(...)`
  - Call existing `upload_doc(workspace, slug, data, filename)` (tools/docs.py:107-150) — writes `docs/<final_name>` + `docs/.meta/<final_name>.json` with sha256/page_count/dedupe inside `project_lock`
  - Delete the source chat-attachment file
  - Return `{final_name}` (post-dedupe)
- Register via `@tool` decorator in `tools/__init__.py` alongside the existing 15+ tools.

### 8. Skill update — `app/skills/emerge_extractor.md:88-120`
Rewrite "Auto-minted project" block. New guidance:

> Pasted/dropped attachments live in `chats/<chat_id>/attachments/`, **not** `docs/`. They are conversational — you can see images via the image block. `docs/` is the **curated sample set** that powers AutoResearch eval, predictions, and review-mode evidence. Files only enter `docs/` via the `promote_attachment_to_docs` tool, and **only after the user explicitly says yes**.
>
> Routing:
> - **Ad-hoc question** ("what's this?", "can you read this?", "识别一下"): answer using the image block. Do not promote, do not upload.
> - **Clear extraction intent** ("extract this", "提取", "build a schema", or user drops 3+ similar files): **ask first** — "要把这 N 张图收进项目样本集（docs/）吗？收进后才能跑提取并保存预测结果。" Only on confirm: call `promote_attachment_to_docs` per file, then proceed with `derive_schema` / `write_schema`.
> - For PDFs, `extract_one` / `extract_batch` require the file in `docs/` — promote first.

Remove the legacy `upload_doc × N` bootstrap text (skill line 114-120) since that pathway is now promote-driven.

---

## Frontend changes

### 1. `src/lib/api.ts`
- Add `attachToChat(slug, chatId, file) → {filename}` — POST `/lab/projects/{slug}/chats/{chatId}/attach`.
- Add `chatAttachmentUrl(slug, chatId, filename) → string` — returns the GET URL for `<img src>`.
- Keep `uploadDoc` (still callable by future "drag onto docs/" sample-management UI; not used by chat paste path anymore).

### 2. `src/components/Chat/ChatPanel.tsx:112-160`
- `_uploadOne` now needs `chatId` — wire from `useChat`'s active chat. Call `attachToChat(selectedSlug, chatId, file)` instead of `uploadDoc(selectedSlug, file)`.
- `retry()` (line 150) — branch on chat path same as initial.
- Empty-hero `_stageOne` unchanged (still uses `/lab/uploads/staging`; the mint block change in backend re-routes the claim target).

### 3. `src/stores/chat.ts:230-279 send()`
- Outgoing attachments now carry `source: "chat"` for the paste path (default). Type: `{ filename: string; stage_token?: string; source: "chat" }`.

### 4. `src/components/Chat/MessageList.tsx` / `UserMessage.tsx`
- For attachments with `source === "chat"` and image extension: `<img src={chatAttachmentUrl(slug, chatId, filename)}>` for thumbnail.
- For `source === "docs"`: existing review-mode link path.
- For PDFs with `source === "chat"`: file chip (no link — user must promote first to see in review mode; agent will offer this).

### 5. `src/components/FSSpine.tsx`
No change. `docs/` count naturally excludes chat attachments because the file lives elsewhere.

---

## Tests

### Update existing
- `tests/integration/test_chat_mint_from_staging.py:74 test_p_unset_with_stage_token_mints_project_and_claims_file` — assert file at `chats/<chat_id>/attachments/<filename>`, NOT `docs/<filename>`. Assert no sidecar at `docs/.meta/`.
- `tests/unit/test_workspace_staging.py:71 test_claim_staged_moves_to_project` — unchanged (legacy `claim_staged` still works; promote-tool uses it under the hood).

### New
- `tests/unit/test_workspace_staging.py` — `test_claim_staged_to_chat_moves_and_dedupes`
- `tests/integration/test_lab_upload.py` — `test_attach_to_chat_endpoint_writes_file_and_returns_filename`, `test_attach_to_chat_dedupes_collisions`
- `tests/integration/test_chat_image_block.py` — `test_image_block_reads_from_chat_attachment_path`
- `tests/unit/test_tool_promote.py` — `test_promote_attachment_to_docs_moves_with_sidecar_and_dedupe`, `test_promote_removes_chat_source_file`
- `tests/integration/test_chat_mint_from_staging.py` — `test_p_unset_renames_placeholder_to_chat_prefix`, `test_mint_files_do_not_enter_docs_dir`

---

## Critical files to modify

| Path | Action |
|---|---|
| `backend/app/workspace/paths.py` | + 2 path helpers |
| `backend/app/workspace/staging.py` | + `claim_staged_to_chat`, factor out dedupe helper |
| `backend/app/chat/service.py` | rewrite mint block 236-296 + `_load_image_blocks` 53-87 + persist `source` on attachments + rename placeholder |
| `backend/app/api/routes/upload.py` | + 2 endpoints (attach POST, attachment GET) |
| `backend/app/tools/promote.py` | NEW |
| `backend/app/tools/__init__.py` | + `promote_attachment_to_docs` tool |
| `backend/app/skills/emerge_extractor.md` | rewrite lines 88-120 |
| `frontend/src/lib/api.ts` | + `attachToChat`, + `chatAttachmentUrl` |
| `frontend/src/components/Chat/ChatPanel.tsx` | `_uploadOne` / `retry` use new endpoint |
| `frontend/src/stores/chat.ts` | persist `source` on attachments |
| `frontend/src/components/Chat/UserMessage.tsx` | dispatch thumbnail URL on `source` |

## Reused (do not reimplement)

- `upload_doc` (backend/app/tools/docs.py:107-150) — atomic write + sidecar + dedupe inside `project_lock`. Used inside new `promote_attachment_to_docs` tool.
- `stage_file` (backend/app/workspace/staging.py:87-119) — unchanged; still the empty-hero path.
- `_dedupe_filename` (backend/app/tools/docs.py:67-82) — factor out to `workspace/paths.py` or `workspace/dedupe.py` so `claim_staged_to_chat` and `upload_doc` share it.
- `atomic_write_bytes` + `project_lock` (workspace helpers) — keep using.

---

## Out of scope (Phase 2 candidates)

- Filtering `Chat-{ts}` projects into a "Drafts" group in `FSSpine` left rail.
- Background cleanup job for stale `Chat-{ts}` projects with 0 promoted attachments after N days.
- A drag-onto-`docs/` UI for explicit sample upload (the `/lab/projects/{slug}/upload` endpoint stays available).
- Migration script for existing `untitled-*` projects — pre-prod, `test_data_deletable` memory applies. Manual cleanup: delete `backend/workspace/untitled-*/` dirs.

---

## Verification

End-to-end flow on a clean workspace:

1. **Empty-hero paste + ad-hoc question**: clear workspace → open frontend → paste image at empty hero → ask "你能识别这个吗" → expect: new `Chat-{ts}` project, `chats/<chat_id>/attachments/image.png` exists, `docs/` empty, FSSpine docs count = 0, agent answers without calling any upload/promote tool.
2. **Empty-hero paste + extract intent**: paste image → "请提取关键字段" → expect: agent asks "要加入样本集吗?" → user says "好" → `promote_attachment_to_docs` runs → file now at `docs/image.png` + sidecar → `derive_schema` runs.
3. **In-project paste**: open existing `us-invoice` → paste a screenshot → ask casual question → expect: file lands in `chats/<chat_id>/attachments/`, NOT `docs/`. FSSpine docs count unchanged.
4. **Image block read**: in (1), check chat log JSONL — user event records `attachments: [{filename, source: "chat"}]`. Agent saw the image inline (response demonstrates understanding).
5. **Promote dedupe**: paste `image.png` twice, promote both → second lands as `image (1).png` in docs/.
6. **Backend tests**: `cd backend && uv run pytest -v` — all new + updated tests green.
7. **Manual UI check**: dev server (`cd /Users/qinqiang02/colab/codespace/ai/emerge && ./dev.sh`), open `127.0.0.1:5173` — paste flow no longer pollutes docs sidebar count.

---

## On approval

Persist this plan to `docs/superpowers/plans/2026-05-14-paste-attachments-vs-docs.md` and add a row to `docs/superpowers/plans/ROADMAP.md`. Execute via subagent per default-execution-mode preference.
