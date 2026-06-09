---
description: Run emerge on a document — extract (or classify/match) and show the result
---

Use the emerge connector to process a document in the current project.

Target: `$ARGUMENTS` (a document filename like `1.jpg`, and/or a project slug; if either is missing, `ws_list(".")` to find the project and `ws_list("{slug}/docs")` to find documents, then ask or pick the first).

Steps:
1. Resolve the project slug and document filename (discover with `ws_list` if not given).
2. Run `extract_one(slug, filename)` with the project's active model — or, if the user named a specific model, register it with `add_model` if needed and run it as an experiment (`create_experiment` → `extract_with_experiment`).
3. Render the structured result as a readable field list. Offer next steps: save as ground truth, run more docs, or compare models.
