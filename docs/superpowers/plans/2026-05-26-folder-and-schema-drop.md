# Folder + non-doc drop: 「交给 agent」是一个动词

## Symptoms (two faces of the same假设错误)

1. **Drop a folder into the composer** → red `1st_batch` chip, agent receives empty `attachments[]`, asks "上面文件夹指的是哪个" and pokes `_staging/` blindly.
2. **Drop a `.yml`** (e.g. another project's exported schema) → red `7_6.yaml` chip, same fate.

Both stem from the same wrong assumption: **the composer treats every drop as "a doc destined for `docs/`"**. Reality:

- `dataTransfer.files` / `clipboardData.files` is a flat `FileList`. A folder shows up as a 0-byte pseudo-File and `stageUpload` 400s.
- Backend `_MAGIC` (`staging.py:38-42` + `upload.py:70-74`) only accepts `pdf/png/jpg`. Anything else 400s.

The fix is to **stop pre-deciding semantics in the composer**. Drop is one verb: 「把这坨东西交给 agent」. Agent decides what it is and asks for a route.

## Out of scope

- Bulk truth-set / csv import (kind=`data`) — surfaced as `kind` on the wire but routed to plain conversation; no new tool yet (wait for real demand).
- Drag-onto-`docs/` UI — orthogonal; covered by future Phase-2 candidates from `2026-05-14-paste-attachments-vs-docs.md`.
- Chrome's File System Access API "open folder" picker — drop/paste suffices for current pain.

## Phase A · Composer recursive drop/paste (frontend)

**File**: `frontend/src/components/Chat/Composer.tsx`

- `handleDrop(e)`: instead of reading `e.dataTransfer.files`, walk `e.dataTransfer.items[i].webkitGetAsEntry()`:
  - `entry.isFile` → `entry.file(cb)` returning a real `File`.
  - `entry.isDirectory` → `entry.createReader().readEntries(cb)` looping until empty (browsers cap each call at ~100 entries) → recurse. Preserve **relative path** in the resolved `File` via a wrapper `{file, relPath}` so chip labels show `folder/sub/foo.pdf` and the user can see what the recursion found.
  - Async-collect into a flat `Array<{file, relPath}>` then call `onAttach(files)`.
- `handlePaste(e)`: same logic on `e.clipboardData.items` (use `getAsEntry()` if present, fall back to `getAsFile()`).
- Empty result (e.g. user dropped an empty folder, or browser doesn't expose entries) → emit one synthetic chip with `status='failed'` + `error` = i18n key `composer.dropEmpty`. **No silent ignore.**
- Type signature shift: `onAttach: (files: File[]) => void` → keep as `File[]` for back-compat; encode `relPath` by setting a non-enumerable `__relPath` only when present, and read it in `ChatPanel.attach`. The `File` API's `webkitRelativePath` is read-only on plain `File` objects and can't be set, so the side-channel is necessary. Comment the why.

**Test**: `Composer.test.tsx` (new) covering:
- single file drop → 1 chip, 1 onAttach call
- folder drop with mock `webkitGetAsEntry` returning 3 nested files → 3 chips, paths preserved
- empty folder drop → 1 failed chip with `composer.dropEmpty` error
- paste with `clipboardData.items` carrying a directory entry → same as drop

## Phase B · Backend widens收件 + emits `kind` (backend)

**Files**: `backend/app/workspace/staging.py`, `backend/app/api/routes/upload.py`

### B.1 Allowlist + sniffing

Add `yaml/yml/json/csv/txt/md` to `_ALLOWED_EXT`. None of these have stable magic bytes, so two-pronged sniff:

- Keep current magic check for `pdf/png/jpg`.
- For text-shaped extensions, verify the bytes are **valid UTF-8** (`data.decode('utf-8')` succeeds) AND don't start with binary magic of an unsupported type. That's the cheap "looks textual" gate without dragging in `python-magic`.
- Cap text payload at 256 KiB (these are config-shaped, not bulk data; bigger means user got the wrong file).

### B.2 `kind` on response

Both `/lab/uploads/staging` and `/lab/projects/{slug}/chats/{cid}/attach` return `{filename, kind}`:

| ext              | kind     |
|------------------|----------|
| pdf/png/jpg/jpeg | `doc`    |
| yml/yaml         | `schema` |
| json             | `schema` (best-effort: if root is a list of `{name,type,...}`, treat as schema; else `other`) |
| csv              | `data`   |
| txt/md           | `note`   |

Implementation: `_classify_kind(filename, data) -> Literal['doc','schema','data','note']` in `staging.py`. Reused by both routes.

### B.3 Persist `kind` on chat-turn `attachments`

`backend/app/chat/service.py` — extend `persisted_attachments` block (around line 302) to carry `kind` if the frontend supplied it. The chat log entry becomes `{filename, source: 'chat', kind?: 'schema'|...}`. `_load_image_blocks` only loads images for `kind in (None, 'doc')` — schemas/notes/data don't get image blocks (they're not visual). Agent reads them via `Read` tool when needed.

### B.4 Tests

- `test_staging.py`: stage `.yaml` → 200, `kind: 'schema'`; stage `.csv` → 200, `kind: 'data'`; stage 300 KiB `.txt` → 400 oversize; stage `.exe` → 400.
- `test_attach_to_chat.py`: same matrix on the in-project route.

## Phase C · Skill: kind-aware routing (agent)

**File**: `backend/app/skills/emerge_extractor.md`

New section after the existing "Pasted/dropped attachments" block:

> **Attachment kinds.** Every chat-attached file carries a `kind`:
>
> - `doc` (pdf/png/jpg) — same as before. Promote to `docs/` only on explicit user intent.
> - `schema` (yml/yaml/json) — likely a schema definition (often exported from another emerge project, or hand-written). **Ask first**: "看到一份 schema 文件 `<name>`。要把它作为本项目字段定义导入吗？这会替换当前 schema." On confirm: call `import_schema_from_yaml(slug, chat_id, filename)`. Never auto-import.
> - `data` (csv) — possibly a truth-set or sample list. Ask the user what to do; no tool yet.
> - `note` (txt/md) — read with `Read` tool when relevant; conversational.

Live-test heuristic: if the user's message also names schema intent ("把这个作为字段", "导入字段"), proceed straight to ask-confirm-import. If only the file dropped with no NL intent, ask first.

## Phase D · `import_schema_from_yaml` tool + HTTP mirror

**Files**: `backend/app/tools/schema.py` (extend), `backend/app/api/routes/schema.py` (new route), `backend/app/tools/__init__.py` (register).

### D.1 Tool

```python
@tool(name="import_schema_from_yaml", ...)
async def import_schema_from_yaml(
    slug: str, chat_id: str, filename: str, *, allow_structural: bool = True
) -> dict:
    """Read a chat attachment (yml/yaml/json), parse as list[SchemaField],
    and replace the project schema. Atomic via existing write_schema path.

    The file must already live in chats/<chat_id>/attachments/<filename>
    (i.e. dropped/pasted into the composer). Refuses if filename's kind
    isn't 'schema' (sniffed from disk on read).

    Returns {field_count, names: [...]} on success.
    """
```

Implementation outline:
1. Resolve `chat_attachment_path(workspace, slug, chat_id, filename)`; 404 if missing.
2. Sniff: extension must be `.yml/.yaml/.json`; bytes must parse as `list`. Otherwise `ValueError("not_a_schema_file")`.
3. `yaml.safe_load` (handles json too) → `list[dict]` → `[SchemaField.model_validate(x) for x in raw]`. Catch `pydantic.ValidationError` → return `{ok: false, error: {error_code: 'invalid_schema_yaml', error_message_en: <pretty>}}`.
4. Call existing `write_schema(workspace, slug, fields=parsed, allow_structural=allow_structural, ...)` — reuse atomic writer + lock.
5. Return summary.

### D.2 HTTP mirror

`POST /lab/projects/{slug}/chats/{chat_id}/attachments/{filename}/import-schema` — thin delegate, body optional `{allow_structural?: bool}`. Symmetry test (`test_symmetry_invariant.py`) auto-covers.

### D.3 Tests

- `test_import_schema_from_yaml.py`:
  - happy path: yaml file with 3 fields → schema replaced, return shape correct.
  - invalid yaml (broken syntax) → 400 with `invalid_schema_yaml`.
  - valid yaml but list of strings (not field dicts) → pydantic error surfaced.
  - file with `.pdf` ext → refused before parse.
  - chat attachment missing → 404.

## Phase E · Verify

- `cd backend && uv run pytest -v` — all green; new tests cover the matrix above.
- `cd frontend && npx tsc --noEmit && npx vitest run` — green.
- Manual smoke (Vite HMR will pick up frontend changes; backend needs `dev.sh` restart):
  - drop a folder containing 2 PDFs → 2 chips, both `staged`/`uploaded`, paths shown.
  - drop the `7_6.yaml` from another project → chip green, `kind=schema`; agent asks "导入吗？"; "好" → schema swapped; ContextSurface field count flips.
- Stop short of full live dogfood per `feedback_milestone_dogfood_handoff` — user runs the final Chrome verify themselves.

## Risk notes

- **`webkitGetAsEntry` is non-standard** but supported in every Chromium-based browser and Safari; Firefox added it 2017. Acceptable surface for a desktop-only lab tool.
- **Schema replacement is destructive.** D.1 routes through `write_schema(..., allow_structural=True)` — same path as a normal agent edit; SSU 不破坏现有 atomic + lock. Agent's "ask first" gate is the user-confirm layer.
- **JSON-as-schema heuristic.** A `.json` that *looks* like a schema (root is list of `{name,type}` dicts) gets `kind=schema`; otherwise falls to `other`. False positives are caught at parse time in D.1.
- Memory `feedback_three_patches_means_missing_noun`: this *is* the missing noun ("attachment kind"). Adding it once instead of patching 3 ext-special-cases.
