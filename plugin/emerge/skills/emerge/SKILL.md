---
description: >-
  Drive emerge — a document-processing colleague — over its remote MCP connector.
  Use when the task involves turning documents into a structured API by extracting
  fields, classifying, matching/reconciling, or auditing documents; building or
  refining an extraction schema; running or comparing models on a project's docs;
  reviewing results and saving ground truth; or publishing a versioned extraction
  API. Triggers on mentions of emerge, a project slug, extract / 提取, 对账, 审核 /
  audit, comparing models, eval / 评分, publishing an API, or working with
  invoices, receipts, or forms in an emerge workspace.
---

# emerge

emerge is a **document-processing colleague**, not a single-purpose tool. You point it at documents and an API emerges — field **extraction** is today's primary capability; **matching/reconciliation** and **compliance audit** run on the same spine. **Slogan: Documents in. APIs emerge. They get better as you correct them.**

You reach emerge through its **remote MCP connector** (tools appear with the `emerge_` service prefix, e.g. `emerge_ws_list`; this doc uses bare names). You are **not** on emerge's filesystem — your Bash/ls can't see the server's disk. Use the connector's tools for everything.

## Narration — never a silent gap

Before your FIRST tool call of a turn, say one short line about what you're doing; same between consecutive tool calls. A silent tool-first turn renders as an empty message in this client.

## The workspace filesystem bus (`ws_*`)

emerge's core objects are just files in the team workspace. These are your `ls`/`cat`/`grep`/`Write`/`Edit`/`mv` over MCP:

- `ws_list(path=".")` — `"."` = all projects; `"{slug}"` = one project; `"{slug}/models"`, `"{slug}/docs"`, …
- `ws_read(path)` — read text/JSON, e.g. `"{slug}/project.json"`. (PDF/image: use `read_doc_image` / `pdf_render_page`, never `ws_read` a binary.)
- `ws_grep(pattern, path=".")` — content search.
- `ws_write(file_path, content)` / `ws_edit(file_path, old_string, new_string, replace_all?)` — create/edit text files (same contract as built-in Write/Edit: old_string must match exactly and be unique).
- `ws_move(source_path, destination_path, copy?)` — `mv`/`cp` inside the workspace; `copy=true` is how you copy a binary doc between projects.

Always **discover before acting**: `ws_list(".")` → pick the slug → `ws_read("{slug}/project.json")`. If a tool named anywhere is absent from your list (minimal surface), the `ws_*` verbs cover the same file operation — e.g. no `read_prompt` → `ws_read("{slug}/project.json")` for `active_prompt_id` → `ws_read("{slug}/prompts/{id}.json")` (its field `description`s + `global_notes` together ARE the prompt; show both).

## Getting the user's files INTO a project

Files the user attaches live in **your sandbox** — the emerge server can't see them; `ws_move` can't reach them and `ws_write` is text-only. Ladder:

1. `request_upload_url(slug, filenames)` → one presigned URL + ready `curl` command per file → run the curls in your own shell.
2. If your sandbox blocks the network (proxy error), hand the user the curl commands to run in their local terminal — the URL is the capability, anyone holding it can push the bytes (15-min expiry; ask for fresh ones if expired).
3. Last resort: the user uploads via the emerge web UI.

Never base64 file content through a tool argument.

## Domain playbooks — read before nontrivial work

`read_skill(domain)` pulls the authoritative playbook (always current with the server). **Call it BEFORE working a task family — "it's just one tool call" is not a reason to skip; playbooks govern how you present results, not just which tools to call**:

- `read_skill("match_audit")` — reconciliation（对账）+ compliance audit（审核）: rules discipline, run/score loop, rendering contracts.
- `read_skill("experiments")` — A/B, compare models, eval rendering, fork/clone.
- `read_skill("review")` — review triage, pre-label.
- `read_skill("attachments")` / `read_skill("self")` — schema import / introduce & configure emerge.

## Core verbs (typed tools — these enforce invariants, so don't hand-write the JSON)

- **Register a model**: `add_model(slug, provider, provider_model_id)` — mints the id + validates. `provider` ∈ `anthropic|openai|google|codex` (Gemini → **google**). Unknown `provider_model_id`? `ws_read` another project's model file. Then `switch_active_model`.
- **Extract one doc**: `extract_one(slug, filename)`, or isolate a variant: `create_experiment(slug, model_id=…)` → `extract_with_experiment(experiment_id, filename)`.
- **Audit a doc group**: `write_audit_rules(slug, audit_rules)` → `run_audit(slug)` → state the overall verdict in one sentence + per-rule list. Long audits may hit a client tool-timeout — just call `run_audit` again: a fresh identical re-run returns the finished report from cache (`cached: true`).
- **Save a correction as ground truth**: `save_reviewed(slug, filename, entities, …)` — this is how emerge "gets better as you correct it."
- **Score / compare**: `score(slug)` or `run_experiment_eval(experiment_id)`. **Print a one-line score after each eval — never a silent gap between back-to-back evals.**
- **Publish a versioned API**: `freeze_version(slug)` → `issue_api_key(slug)` → served at `POST /v1/{pid}/extract`. Run `readiness_check` / `contract_diff` first.

## Red lines (never cross)

- **Audits go through `run_audit`** — never pull doc images into the conversation to judge them yourself; the server judge sees full-resolution originals and produces a persistent report.
- **Audit rules are group-invariant** — write relations between document roles, never the current group's literal values (details: `read_skill("match_audit")`).
- **Never hand-write `models/*.json`** and never edit schema except via `write_schema` — ids + shapes are invariants (`schema.json` is hard-blocked in `ws_write`/`ws_edit`).
- **Experiments never auto-promote.** Only `promote_experiment` flips the active pair, and only when the user asks.
- **To teach the model, edit `description` / `global_notes`** — never image few-shots, never coordinates in the prompt.
- **Secrets are unreadable** — `.env`, keys, `_auth/` are blocked server-side. Don't try.
- **Deleting a whole project** uses `delete_project(slug)` — confirm first; unrecoverable.

When unsure which slug/model/doc to use, **`ws_list` and look** rather than guessing.
