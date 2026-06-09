---
description: >-
  Drive emerge — a document-processing colleague — over its remote MCP connector.
  Use when the task involves turning documents into a structured API by extracting
  fields, classifying, or matching documents; building or refining an extraction
  schema; running or comparing models on a project's docs; reviewing results and
  saving ground truth; or publishing a versioned extraction API. Triggers on
  mentions of emerge, a project slug, extract / 提取, comparing models, eval / 评分,
  publishing an API, or working with invoices, receipts, or forms in an emerge
  workspace.
---

# emerge

emerge is a **document-processing colleague**, not a single-purpose tool. You point it at documents and an API emerges — field **extraction** is today's primary capability; **classification** and **matching** grow on the same spine. **Slogan: Documents in. APIs emerge. They get better as you correct them.**

You reach emerge through its **remote MCP connector** (these tools appear as `emerge` / `mcp__emerge__*`). You are **not** on emerge's filesystem — your Bash/ls can't see the server's disk. Use the connector's tools for everything.

## Discover with the `ws_*` filesystem tools

emerge's core objects are just files in the team workspace. Read them to learn what exists — this is your `ls`/`cat`/`grep`:

- `ws_list(path=".")` — list. `"."` = all projects; `"{slug}"` = one project; `"{slug}/models"` = its models; `"{slug}/docs"` = its documents.
- `ws_read(path)` — read a text/JSON file, e.g. `"{slug}/project.json"`, `"{slug}/models/{id}.json"`, `"{slug}/predictions/_draft/{f}.json"`. (PDFs/images: use `read_doc_image` / `pdf_render_page` — never `ws_read` a binary.)
- `ws_grep(pattern, path=".")` — search file contents, e.g. find which project/model mentions a value.

Always **discover before acting**: `ws_list(".")` → pick the project slug → `ws_read("{slug}/project.json")`.

## Core verbs (typed tools — these enforce invariants, so don't hand-write the JSON)

- **Register a model**: `add_model(slug, provider, provider_model_id)` — mints the id + validates. `provider` ∈ `anthropic|openai|google|codex` (Gemini → **google**). Don't know the `provider_model_id`? `ws_read` another project's model file to copy it. Then `switch_active_model` to make it active.
- **Extract one doc**: `extract_one(slug, filename)` (uses the active model), or isolate a variant with `create_experiment(slug, model_id=…)` → `extract_with_experiment(experiment_id, filename)`.
- **Save a correction as ground truth**: `save_reviewed(slug, filename, entities, …)` — the corrected result becomes the standard answer that scoring grades against. This is how emerge "gets better as you correct it."
- **Score / compare**: `score(slug)` for the active setup, or `run_experiment_eval(experiment_id)` per experiment. To compare two models: make an experiment for each, eval both, then show a table (model · overall% · per-doc%) and call out which fields drove the gap. **Print a one-line score after each eval — never leave a silent gap between back-to-back evals.**
- **Publish a versioned API**: `freeze_version(slug)` then `issue_api_key(slug)` → the project is served at `POST /v1/{pid}/extract`. Run `readiness_check` / `contract_diff` first.

## Red lines (never cross)

- **Never hand-write `models/*.json` or `prompts/*.json`** — use `add_model` / the schema tools. The id + shape are invariants.
- **Experiments never auto-promote.** Only `promote_experiment` flips the active pair, and only when the user asks.
- **To teach the model, edit `description` / `global_notes`** — never add image few-shots, never put coordinates in the prompt.
- **Secrets are unreadable** — `.env`, keys, `_auth/` are blocked server-side. Don't try.
- **Deleting a whole project** uses `delete_project(slug)` (it tombstones safely) — confirm first; it's unrecoverable.

## The full playbook lives on the connector

This skill is the orientation. For the complete discipline — schema editing, the autoresearch `/improve` loop, the publish gate, the experiment axis, rendering contracts — the connector exposes the **`emerge-extractor`** MCP prompt. Load it when you're doing nontrivial work; it's the single source of truth and stays current with the server.

When unsure which slug/model/doc to use, **`ws_list` and look** rather than guessing.
