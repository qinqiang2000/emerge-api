---
description: Improve an emerge project's accuracy by refining the schema against reviewed ground truth
---

Use the emerge connector to refine the project's extraction quality.

Input: `$ARGUMENTS` (project slug, optionally the fields to focus on; discover with `ws_list(".")` if missing).

Steps:
1. Check the current state: `score(slug)` and `ws_read` a few `reviewed/*.json` vs `predictions/_draft/*.json` to see where the model misses.
2. The lever for teaching the model is the prompt's `description` / `global_notes` — never image few-shots, never coordinates. Propose concrete wording changes for the fields that miss, and apply them through the schema tools (not by hand-writing `prompts/*.json`).
3. For a systematic, multi-doc improvement loop, kick off autoresearch with `start_job` (it proposes description tweaks, scores against reviewed, and picks the best candidate — but **never auto-promotes**; the user activates explicitly).
4. Re-`score` and report the before/after. Keep the user in the loop on every promotion.
