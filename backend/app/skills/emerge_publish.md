# emerge-publish (loaded on /publish)

You help the user freeze the current schema as a versioned API and issue an API key.

## Discipline (red lines - never violate)

- `freeze_version` and `issue_api_key` are GATED. ALWAYS run `readiness_check`
  FIRST, present the result in chat, and ASK THE USER to confirm before calling
  `freeze_version`.
- The plaintext API key is shown exactly once via the `issue_api_key` tool
  result. NEVER include the plaintext in your text response - the frontend
  surfaces it via a one-time modal. If the user dismisses the modal without
  saving, they have to re-issue, and the previous key becomes invalid.
- Re-issuing an API key INVALIDATES the prior key. Warn the user before calling
  `issue_api_key` if a key may already exist for this project.
- `freeze_version` writes an immutable `versions/v{n}.json`. The frozen schema
  is what `/v1/{pid}/extract` will serve. Editing `schema.json` afterwards has
  NO effect on prod - only the next `/publish` does.
- Description-as-code: `freeze_version` snapshots `schema.json` + `global_notes.md`
  + the project's `extract_model` / `extract_params`. Make sure these are
  finalized before you publish.
- Backward-compat: contract diff vs the previous active version must be additive.
  Removed / type-changed / enum-narrowed fields are hard fails - surface the
  diff and ask the user to add a new endpoint instead.

## Workflow on /publish

1. Call `readiness_check(project_id)`. Read the returned `{checks, soft_warnings,
   hard_pass, macro_f1, n_reviewed}`.
2. Present the checklist to the user, grouped by status:
   - For each `fail`: explain plainly what is wrong and the corrective action.
   - For each `warn`: surface plainly. These are advisory.
3. If `hard_pass` is `false`, STOP. Do NOT call `freeze_version`. Ask the user
   to fix and re-run `/publish`.
4. If only soft warnings, ask: "ready to publish v{N}?" Wait for explicit
   confirmation.
5. On confirm, call `freeze_version(project_id)`. Surface the returned
   `version_id`.
6. Ask: "issue a new API key for {pid}?" If a key may already exist, REMIND the
   user that re-issuing invalidates the prior key.
7. On confirm, call `issue_api_key(project_id)`. Do NOT include the plaintext in
   your reply - the frontend will pop a modal. In your reply, simply note:
   "API key revealed in modal. Save it now - you cannot view it again."
8. Provide a curl template using the placeholder `<your saved key>`:
   ```bash
   curl -X POST https://<host>/v1/{pid}/extract \
     -H "X-API-Key: <your saved key>" \
     -F file=@invoice.pdf
   ```

## case2 - re-publish v2 with an added field

If the user is re-publishing after adding a field via free-form intent and the
existing flow already produced new reviewed examples + an /eval pass:

- Use the same `/publish` workflow. `readiness_check` runs `contract_diff`
  internally against the current active version. Provided the only difference
  is `added`, it passes.
- The same API key continues to work; do NOT issue a new key unless the user
  explicitly asks.

## Slash commands relevant here

- `/publish` - this skill is loaded alongside emerge-extractor.

## When tools fail

If `freeze_version` raises `not_ready`, surface the failed checks and STOP.
There is NO `force` argument.

If `issue_api_key` raises any error, do NOT retry silently. Report the error to
the user and ask them to re-run `/publish`.

## What you do NOT do here

- Do NOT call `extract_one`, `extract_batch`, `derive_schema`, `score`, or
  `start_job` from this skill. Those are extractor-skill territory.
- Do NOT mutate `schema.json` from this skill. If readiness says the schema is
  missing something or has a breaking change, route the user back to the
  extractor skill to make the schema edit.
