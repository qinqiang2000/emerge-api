---
description: Compare two models on an emerge project and show which is more accurate
---

Use the emerge connector to compare models on a project's documents.

Input: `$ARGUMENTS` (project slug and/or the two models to compare; discover with `ws_list` if missing — `ws_read("{slug}/project.json")` for the current active model, `ws_list("{slug}/models")` for registered ones).

Steps:
1. For each model being compared: register it with `add_model` if it isn't in `ws_list("{slug}/models")` yet, then `create_experiment(slug, model_id=…)`.
2. Extract the target doc(s) for each experiment (`extract_with_experiment`), then `run_experiment_eval(experiment_id)` for each.
3. **Print a one-line score after each eval** (model · overall% · per-doc%) — don't leave a silent turn between evals.
4. Once all evals finish, show a comparison table (model | overall | per-doc) and name the fields that drove the gap. Suggest a `description`/`global_notes` tweak if a systematic miss appears. Do **not** promote anything automatically.
