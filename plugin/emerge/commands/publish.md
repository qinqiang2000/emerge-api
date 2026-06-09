---
description: Freeze an emerge project as a versioned API and issue an API key
---

Use the emerge connector to publish the project as a production extraction API.

Input: `$ARGUMENTS` (project slug; discover with `ws_list(".")` if missing).

Steps:
1. Run `readiness_check(slug)` and `contract_diff(slug)` first — surface any blockers (accuracy below the publish gate, breaking schema changes) before freezing.
2. If ready, `freeze_version(slug)` to snapshot the current schema as an immutable version, then `issue_api_key(slug)`.
3. The frozen project is served at `POST /v1/{pid}/extract` — give the user the key (shown once) and a short curl example. Confirm before issuing; the key is reveal-once.

Note: publish artifacts are global production state — they are written to the true root, not the team workspace, so they survive independent of lab edits.
