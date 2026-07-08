<!-- backend/app/skills/emerge_autoresearch.md -->
# emerge-autoresearch (loaded on /improve)

You are running the autoresearch loop on top of the extractor skill. Your job
on this turn is to KICK OFF a background job - not to run the loop yourself.

## Discipline (red lines - never violate)

- AutoResearch NEVER auto-promotes. The job writes candidates to
  `versions/_candidate/{job_id}/turn_{k}.json`. The user must explicitly
  click "accept" to overwrite `schema.json`.
- The proposer LLM may only edit `description` text. Field add/remove/
  rename/retype is forbidden - the job's response_schema enforces this and
  rejects violations as proposer_failed events.
- Counterexample triplets (M3 territory) must NEVER enter the proposer prompt.
  In M2C only `_notes` from reviewed examples feed the proposer as
  high-priority hints.
- Bound by `max_turn` and `early_stop_no_improvement`. No token / $ budget.

## Two shapes: broad vs focused

- **Broad** `/improve` — all-field tune. Needs signal across the schema, so it
  keeps the ≥5-reviewed floor.
- **Focused** `/improve <field…>` — a single hot field the user keeps fixing
  ("salesOrderNumber keeps splitting wrong"). Pass `target_fields` so the
  proposer only rewords those descriptions and the headline is graded on them
  alone. Because the human still hand-clicks Accept (the real gate) and the
  blast radius is one description, the floor relaxes to **≥1 reviewed doc that
  contains the field**. This is the path the review-bar "optimize this field"
  button drives directly (no chat needed).

## Workflow on `/improve`

1. Count reviewed examples: `Glob {CURRENT_PROJECT_DIR}/reviewed/*.json`
   (top level only — `_pending/` drafts don't count; remote client:
   `ws_list("{slug}/reviewed")`).
   - **Broad** (no specific field named): if fewer than 5 reviewed examples
     exist, stop — tell the user "/improve needs >=5 reviewed examples to have
     signal - you currently have N. Please /review more docs first." Do NOT
     call `start_job`.
   - **Focused** (user named a field, or the surface-context
     `corrections_by_field` points at a clear hot field): only require ≥1
     reviewed doc containing that field.
2. Otherwise call `start_job` with:
   ```
   {"skill": "autoresearch", "slug": <slug>,
    "params": {"max_turn": 30, "early_stop_no_improvement": 5}}
   ```
   For a focused run add `"target_fields": ["<field>", ...]` to `params`.
   The tool returns a `job_id` string.
3. Tell the user briefly: "Started autoresearch (job <id>). The progress
   card below streams per-turn field accuracy. You can pause / cancel at
   any time, and accept the best candidate when you're satisfied."

The loop optimizes against `field_accuracy_macro` (M12.x — was macro_f1
before; the per-turn events still emit the old key as a transitional
alias with the same value, so legacy JSONL readers don't break).

Do NOT call extract_one / score yourself in the /improve turn — the
job loop owns those.

## Tune is description-only — structural changes go elsewhere

A focused/broad tune can only reword field **descriptions**. If a correction
implies the *schema shape* is wrong, that is NOT a tune:

- **Remove a field** ("this column is junk / never present"): one
  `write_schema` call dropping it (`allow_structural=true`). Cheap, no eval
  gate — it's a lab edit.
- **Add a field** ("we also need `dueDate`"): `write_schema` to add it, then
  the docs must be re-labeled / re-extracted to populate values. Heavier than a
  tune; it is not what the review-bar "optimize this field" button does (you
  can't focus a field that doesn't exist yet).

So: keep `start_job` for description refinement; route add/remove/rename/retype
through `write_schema`. Never try to smuggle a structural change through the
proposer — the candidate accept gate rejects it.

## Slash commands relevant here

- `/improve` - entry point handled by this skill.
- `/pause`, `/resume`, `/cancel` - direct frontend buttons on the job card.
  If the user types them in chat, call `pause_job` / `resume_job` /
  `cancel_job` with the most recent `job_id`.

## When the job ends

The frontend's progress card subscribes to `/lab/jobs/{job_id}/events` and
shows the user the best candidate. Acceptance is a UI button calling
`/lab/projects/{slug}/schema/accept-candidate` directly - you do NOT
overwrite `schema.json` from chat.
