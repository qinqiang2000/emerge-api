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

## Workflow on `/improve`

1. Call `list_reviewed(slug)`. If fewer than 5 reviewed examples exist, stop
   here: tell the user "/improve needs >=5 reviewed examples to have signal -
   you currently have N. Please /review more docs first." Do NOT call
   `start_job`.
2. Otherwise call `start_job` with:
   ```
   {"skill": "autoresearch", "slug": <slug>,
    "params": {"max_turn": 30, "early_stop_no_improvement": 5}}
   ```
   The tool returns a `job_id` string.
3. Tell the user briefly: "Started autoresearch (job <id>). The progress
   card below streams per-turn F1. You can pause / cancel at any time, and
   accept the best candidate when you're satisfied."

Do NOT call extract_one / extract_batch / score yourself in the /improve
turn - the job loop owns those.

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
