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
- Re-issuing an API key INVALIDATES the prior key for that user. Warn the
  user before calling `issue_api_key` if a key may already exist for this
  user (one live key per `user_id`; default `user_id` is `"default"`).
- `freeze_version(slug)` writes BOTH artifacts atomically:
  - `versions/v{n}.json` inside the project folder — the lab-side publish
    lineage; lives next to `schema.json`, used by `contract_diff` for the
    next publish's backward-compat gate.
  - `_published/{pub_xxx}.json` at workspace root — the frozen, immutable
    artifact (`schema`, `model_id`, `params`, `global_notes`) that the
    public `POST /v1/extract` endpoint serves. Self-contained so it
    survives a project rename or delete. **emerge is staging**: the
    `published_id` is what gets synced to a production deployment, where
    the same frozen artifact gets called. The same URL shape works for
    both.
  Returns `{version_id, published_id}`. Editing `schema.json` afterwards
  has NO effect on a frozen `pub_xxx`.
- Description-as-code: `freeze_version` snapshots the active prompt's
  schema + `global_notes` + the active model's `provider_model_id` /
  `params`. Make sure these are finalized before you publish.
- Backward-compat: contract diff vs the previous active version must be
  additive. Removed / type-changed / enum-narrowed fields are hard fails —
  surface the diff and ask the user to add a new endpoint instead.

## Workflow on /publish

1. Call `readiness_check(slug)`. Read the returned `{checks, soft_warnings,
   hard_pass, field_accuracy_macro, n_reviewed}` envelope. The hard gate
   is `field_accuracy_macro >= 0.75`; the soft band is `[0.75, 0.90)`.
   (`macro_f1` is mirrored under its old key as a transitional alias and
   carries the same accuracy value — prefer the new key.)
2. **Rendering contract:**
   - **browser** (`interface: browser`): the lab UI renders the readiness
     checklist automatically (as a PublishStage panel inline with this
     turn). **Do NOT reproduce it as a markdown table or bullet list.**
     Give one short narrative: if `hard_pass` is `true`, say so and name
     the next version number; if `false`, name the failing check(s) and
     what to fix (omit passing checks — the UI shows them); mention
     `soft_warnings` in one phrase if present.
   - **headless** (`interface: headless`): render the full checklist as a
     markdown list, failures first:
     - `- ❌ **{check_label}**: {detail}` for failed checks
     - `- ✅ {check_label}: {detail}` for passed checks
     Then your one-line narrative (same rule as browser).
3. If `hard_pass` is `false`, STOP. Do NOT call `freeze_version`. Ask the user
   to fix and re-run `/publish`.
4. If only soft warnings, ask: "ready to publish v{N}?" Wait for explicit
   confirmation.
5. On confirm, call `freeze_version(slug)`. Surface the returned
   `version_id` and `published_id` (the latter is what clients call).
6. Ask: "issue a new API key for the default user?" If a key may already
   exist for that user, REMIND the user that re-issuing invalidates the
   prior key. Keys are user-scoped — one key calls *any* `published_id`,
   so you don't have to issue a fresh key per project.
7. On confirm, call `issue_api_key(user_id="default")`.
   **Rendering contract:**
   - **browser** (`interface: browser`): **Do NOT include the plaintext key
     in your reply** — the frontend pops a one-time modal. Give one
     sentence: "Key minted — copy it from the card above before closing;
     it won't be shown again."
   - **headless** (`interface: headless`): the plaintext key is in the
     tool result (field `key_plaintext`). **Print it verbatim in a code
     block** so the user can copy it, and warn once that it won't be
     shown again:

     ```
     EMERGE_API_KEY=ek_…
     ```

     **Save this key now — it won't be shown again.**

     Do NOT omit or truncate the key in headless mode. Then always print
     the curl snippet:

     ```sh
     curl -X POST https://<host>/v1/extract \
       -H "X-API-Key: $EMERGE_API_KEY" \
       -F "published_id=<pub_xxx>" \
       -F "file=@/path/to/document.pdf"
     ```

   **browser**: Mention the curl snippet only if the user asks.

## case2 - re-publish v2 with an added field

If the user is re-publishing after adding a field via free-form intent and the
existing flow already produced new reviewed examples + an /eval pass:

- Use the same `/publish` workflow. `readiness_check` runs `contract_diff`
  internally against the current active version. Provided the only difference
  is `added`, it passes.
- The same API key continues to work; do NOT issue a new key unless the user
  explicitly asks. The user's key works with the NEW `published_id` too —
  one key, any `pub_xxx`.

## Slash commands relevant here

- `/publish` - this skill is loaded alongside emerge-extractor.

## When tools fail

If `freeze_version` raises `not_ready`, surface the failed checks and STOP.
There is NO `force` argument.

If `issue_api_key` raises any error, do NOT retry silently. Report the error to
the user and ask them to re-run `/publish`.

## What you do NOT do here

- Do NOT call `extract_one`, `derive_schema`, `score`, or
  `start_job` from this skill. Those are extractor-skill territory.
- Do NOT mutate `schema.json` from this skill. If readiness says the schema is
  missing something or has a breaking change, route the user back to the
  extractor skill to make the schema edit.
