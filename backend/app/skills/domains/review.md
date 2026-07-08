<!-- domain skill: review mode + ui driving + pre-label — pulled via read_skill("review") -->
# Review mode · UI driving · Pro labeler

## Review-mode feedback triage

When a turn carries a `## Review focus` block, the user is in review
mode and has selected a specific cell to talk about. Default-route to the
lowest-commitment action:

1. **Value correction** ("应该是 2024-03-12", "this is wrong, it's
   ACME"): fix one value on one doc.
   → `Read predictions/_draft/{filename}.json` → patch entity →
   `save_reviewed` (carry forward existing `_notes` and `_notes_consumed`).
2. **Behavior hint** ("这个字段不该等于 PO 号", "always strip currency"):
   teach about this doc-field, not yet asserting a global rule.
   → `Read reviewed/{filename}.json` (if it exists) → set `_notes[field]`
   → `save_reviewed`. AutoResearch will pick this up next `/improve`
   turn. Reply with one short sentence confirming. Do NOT also call
   `write_schema`.
3. **Global rule** ("for ALL invoices…", "across the whole project…"):
   user is asserting policy. Call `write_schema(slug, schema=<current fields>,
   global_notes="<new text>")` — no confirm needed for pure text edits.
4. **Schema description edit** ("the description for buyer_name should
   mention…"): rewrite that field's description.
   → `Read prompts/{active_prompt_id}.json` → mutate description →
   `write_schema`. No confirm.
5. **Structural change** ("we need a separate `tax_id` field"): same
   gate as outside review — propose diff, ask confirmation, then
   `write_schema(allow_structural=true)`.

**Auto-route. Do NOT ask** "do you want me to save this as a note or
edit the description?" The UI surfaces a chip after `save_reviewed` for
the user to escalate when they want.

**Bind every tool call to the filename from `## Surface context`**, NOT
to any filename the user mentions later in the same turn. The user may
navigate to the next doc mid-response.

## Ambient tune nudge

The review `## Surface context` carries `corrections_since_tune` (fields
changed since the last accepted tune), `reviewed_count`, and — when present —
`corrections_by_field` (a per-field tally like `salesOrderNumber×3,
currency×1`).

Offer a tune when EITHER signal is strong:
- **Focused** — any single field in `corrections_by_field` has been corrected
  **≥2 times**: the user clearly keeps fixing the same field. Offer a focused
  run scoped to it: "`salesOrderNumber` 已被你修正 3 次，要我 `/improve` 聚焦优化
  这个字段吗？" (this maps to `/improve` with `target_fields`).
- **Broad** — `corrections_since_tune >= 3`: enough scattered edits to be worth
  a full pass: "你已修正 N 处，要我 `/improve` 一下 prompt 吗？"

Add at most ONE such line, after handling the user's actual message. Just
offer — never auto-run `/improve` or `start_job`. Below both thresholds, say
nothing. Note the review bar also shows a non-chat "optimize this field"
button from the same signal, so the user may already have an entry point —
keep the nudge to one short line.

## Driving the review UI

> **headless** (`interface: headless`): the `ui_*` tools are browser
> side-channel only — there is no viewer to receive them. **Skip all
> `ui_*` calls entirely.** Replace with a one-line narration in your
> text reply, e.g. "→ page 3" / "→ focus field buyer_name" / "→ switch
> to experiment tab". `get_surface_state` is still useful in headless
> (it reads disk state, not browser state) — call it when you need
> review_status / prediction presence.

When the surface context is `review` (`interface: browser`), five `ui_*`
tools push navigation commands to the client, and `get_surface_state`
reads disk truth about the current doc. All six take `slug` + `filename`;
`slug` is from `## Active context`, `filename` is from `## Surface context`.

- `ui_open_review(slug, filename)` — open review mode on a doc **from the
  chat surface** (the agent-side twin of clicking the doc row in the
  spine). The only `ui_*` tool that works without an open viewer — this is
  how `/review` lands on the first un-reviewed doc and how "打开 xxx.pdf"
  is honored. headless: narrate `→ review <filename>` and give the link
  `{base}/p/{slug}?review=<filename>` instead.
- `ui_goto_page(slug, filename, page)` — jump the PDF viewer to page N
  (1-indexed). "跳到第 5 页" / "go to page 3 of this doc" → call.
- `ui_set_active_field(slug, filename, path)` — focus a field row.
  "高亮 buyer_name" / "jump to the amount field" → call. `path` matches
  the editor's field identifier (`buyer_name`,
  `line_items[0].amount`).
- `ui_set_active_tab(slug, filename, tab_key)` — switch tab. `'active'`
  selects the saved annotation; any other value is treated as an
  experiment_id.
- `ui_set_active_entity(slug, filename, idx)` — switch entity tab in a
  multi-entity doc. `idx` is 0-indexed.
- `get_surface_state(surface='review', slug, filename)` — returns
  `review_status` ('unprocessed' | 'pending' | 'reviewed'),
  prediction/reviewed presence, page_count, evidence pages, notes, and
  the list of experiments that have a prediction for this doc. Call when
  the user asks "这个 doc 啥状态" / "pending 啥意思" / "did exp_xyz run
  on this" — answer from the returned payload rather than inventing.
  Phase 1 does NOT compute schema drift; do not claim drift detection.
- `read_doc_image(slug, filename, page)` — pull the visual content as an
  inline image. Use when the user asks about visible content ("这是什么
  文档", "这张图里写的啥", "is the receipt blurry") and the JSON state
  from `get_surface_state` isn't enough. PDF: pass `surface_context.page`;
  PNG/JPG: page=1.

  **Pull, not push.** We do NOT auto-attach the current doc to every
  review turn — vision tokens are only paid when you call this tool. If
  the question is about labels, descriptions, or schema state, answer
  from JSON tools (`Read` on `predictions/_draft/`, `reviewed/`, the
  active prompt; `get_surface_state`) without calling this one. Do NOT
  call `extract_one` just to "see" a doc — extract
  produces structured JSON via a separate LLM call; `read_doc_image`
  gives you direct vision at no extra LLM cost.

`ui_*` actions don't touch disk — they're pure navigation. Execute
directly without confirming.

## Pro labeler (pre-label)

A stronger / slower model drafts labels for the human boss to verify.
Trigger phrases: "pro 先标一版", "用大模型预标这批", "labeler 跑一遍".

Two entry points depending on batch size:

- **Single file / ≤10 files (atomic)**: call `label_docs(slug,
  filenames=[...], labeler_model?)` directly. Writes to
  `reviewed/_pending/{filename}.json`. Skips docs already in `reviewed/`
  (human wins) or with an existing `_pending/` draft (idempotent —
  re-running the same call after a disconnect is a no-op).
- **Batch (>10 files)**: delegate to the `pre_label_runner` subagent via
  the SDK `Agent` tool. The subagent loops `label_docs` in 5-10 file
  chunks, narrates progress between batches, and soft-fails per doc.
  Resume after disconnect is automatic — re-invoke the same Agent call
  and idempotent skip handles the rest. Example invocation:
  `Agent(subagent_type="pre_label_runner", prompt="Pre-label these 30 files in project <slug>: [a.pdf, b.pdf, …]")`.
  Always confirm with the user before invoking for >30 files.

- To know which model will run, call `get_labeler_config(slug)`. Do NOT
  `Read project.json` to pre-check — `labeler_model` is normally null
  and the env fallback (`EMERGE_DEFAULT_LABELER_MODEL`) resolves it.
- `set_labeler_model(slug, model_id)` only when user asks to lock a
  project to a model, or `label_docs` returned `labeler_model_not_configured`.

Hard rules: `label_docs` output never lands in `predictions/_draft/` or
`reviewed/` — only in `_pending/`. Only `save_reviewed` (Save click)
promotes to ground truth.

## After a user correction (anywhere, not just review mode)

("buyer_name should be ACME Sdn Bhd"): `Read
predictions/_draft/{filename}.json` → patch entity in memory →
`save_reviewed`. Don't just acknowledge in chat without saving.
