<!-- domain skill: chat attachments / schema import / empty-hero — pulled via read_skill("attachments") -->
# Attachments vs sample docs

Pasted/dropped attachments live in `chats/<chat_id>/attachments/`, **not**
`docs/`. They are conversational — you can see images via the image block.
`docs/` is the **curated sample set** that powers AutoResearch eval,
predictions, and review-mode evidence. Files only enter `docs/` via the
`promote_attachment_to_docs(slug, chat_id, filename)` tool, and **only
after the user explicitly says yes**.

When the user drops files into the empty-hero state, the backend
pre-creates the project (with a placeholder name like `Chat-260514-093012`)
and the attachments are already in `chats/<chat_id>/attachments/` when you
receive control. There is nothing to upload.

(Remote client? The user's attached files live in YOUR sandbox, not on the
emerge server — see the core skill's "Getting the user's files INTO a
project" for the `request_upload_url` flow.)

## Attachment kinds

Every chat-attached file carries a `kind` (sniffed from extension + bytes
at staging time):

- `doc` (pdf/png/jpg) — same as before. Promote to `docs/` only on
  explicit user intent.
- `schema` (yml/yaml; or json that looks like a `[{name,type,...}]`
  list) — likely a schema/prompt definition (often exported from another
  emerge project, or hand-written; in emerge a prompt = schema fields +
  global_notes, so "导入 prompt" and "导入 schema" mean this same object).
  **Ask first**, and offer two targets, not just replace:
  "看到一份 schema 文件 `<name>`。① 替换当前 active prompt 的 schema，或
  ② 导入为一个新的 prompt 变体（保留现有的，便于 A/B）？"
  - 替换 → `import_schema_from_yaml(slug, chat_id, filename)` (default).
  - 新变体 → `import_schema_from_yaml(slug, chat_id, filename,
    as_new_variant=True)`; this leaves the active prompt untouched and
    mints `prompts/{new_id}.json`. After it returns, tell the user the new
    variant exists and that adopting it needs an explicit
    `switch_active_prompt` (never auto-switch).
  **Always call the tool directly — never hand-convert the file first.** It
  accepts both emerge's native field list AND a foreign JSON-Schema / Gemini
  / OpenAI prompt config (root dict with `prompt_template.json_schema`, or a
  raw JSON-Schema with `properties`/`items`/`anyOf`): the tool transcodes it
  (unwraps array roots, merges anyOf variant branches, drops nullable
  branches, folds `required` arrays). On a converted import the result carries
  `converted_from: "json-schema"` + `notes` — relay the notes so the user sees
  what was inferred. If the tool returns `invalid_schema_yaml` listing
  per-field problems, fix exactly those fields and re-import once; the error
  aggregates every problem, so there's no need to retry field-by-field.
  Never auto-import. If the user's message itself names schema intent
  ("把这个作为字段", "导入字段", "用这个 schema", "导入这个 prompt"),
  proceed straight to the ask-which-target confirm. If only the file
  dropped with no NL intent, ask first. When the user's wording implies
  replacement ("这是最新的 / 更新一下"), default the recommendation to
  替换; when it implies comparison ("再加一个 / 对比一下"), recommend 新变体.
- `data` (csv) — possibly a truth-set or sample list. Ask the user what
  to do; no tool wired yet. **But** if the user's intent is to run the
  project's schema over it (校验/提取/审核 a text/tabular file), treat it as
  a promotable text doc — see "Text files as extract targets" below.
- `note` (txt/md; or json that isn't a `[{name,type}]` schema list) — by
  default conversational: `Read` it when relevant. **But** a text/JSON file
  the user wants the schema run against is a doc, not a note — see below.

## Text files as extract targets (txt/md/json/csv/yaml)

`docs/` and the extract pipeline accept **text files**, not just pdf/png/jpg.
A JSON/txt/csv the user wants validated or extracted (e.g. "校验这个 JSON",
"按规则判断这份文件", "extract this config") is a real sample doc — even
though it staged as `kind=note`/`data`/`schema` (that classification is a
best-effort hint, not a hard gate). The model reads the raw text and emits
the same schema-driven structured output as for a scanned document; text
carries no coordinates, so review shows the raw text with no field
highlighting (expected).

When the user shows that intent on a text/JSON/csv attachment, route it the
SAME way as a doc: **ask first** ("要把 `<name>` 收进项目样本集（docs/）按
当前 schema 跑校验/提取吗？"), then on confirm
`promote_attachment_to_docs(slug, chat_id, filename)` → `extract_one` (or
`derive_schema` → `write_schema` → `extract_one` if the schema isn't set up
yet). Do NOT dead-end a text file as "just a note" when the user clearly
wants extraction. The schema-import path (kind=schema, above) still wins when
the file IS a field definition and the intent is "导入 schema/prompt" — the
disambiguator is the user's intent, not the extension.


## Routing for chat attachments

- **Ad-hoc question** ("what's this?", "识别一下"): answer using the image
  block directly. Do **not** promote, do **not** call `derive_schema`.
- **Reference to a `docs/` file the user did NOT just paste**: that file
  is not in the current turn's image blocks (we don't auto-attach). Call
  `read_doc_image(slug, filename, page)` to pull vision. Do NOT ask the
  user to re-paste — they can see the file in the UI; we just need a pull
  instead of a push.
- **Clear extraction intent** ("extract this", "提取", "校验这个",
  "build a schema", user drops 3+ similar files): ask first —
  "要把这 N 份文件收进项目样本集（docs/）吗？" Only on confirm: call
  `promote_attachment_to_docs` per file, then proceed with
  `derive_schema` → `write_schema` → parallel `extract_one` per file.
  Works for **text files (json/txt/csv/md) too**, not just images — see
  "Text files as extract targets" above.
- **PDFs / text files**: `extract_one` requires the file in `docs/` —
  promote first (same ack rule). Applies to any non-image doc (pdf and the
  text extensions alike).

## On the first turn after an empty-hero drop

1. **Do NOT** call `create_project` — it already happened.
2. **DO** rename the project if the user's message implies one:
   `Bash mv {WORKSPACE_ROOT}/Chat-260514-093012 {WORKSPACE_ROOT}/<new-slug>`.
   The user can also leave the placeholder if the project stays
   conversational scratch.
