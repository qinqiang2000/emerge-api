# emerge terminology

> Single source of truth for the **nouns** and **verbs** the app manages.
> Whenever new UI copy, tool names, or disk paths are added, check the term here
> first. If a needed term is missing, add it in one PR — don't ship a synonym.
>
> Rule of thumb: the user-visible label matches the on-disk noun whenever there
> is one on disk.

## Objects (nouns)

| Term | Lives on disk as | Surface (UI label) | What it is |
|---|---|---|---|
| **project** | `workspace/{pid}/` | left-rail row (`~/projects/`) | The unit of fork / publish / API key. One folder. |
| **doc** | `{pid}/docs/{doc_id}.{ext}` (+ `.meta.json`) | `docs/` spine group, "doc" in chat copy | A PDF/image the user uploaded. Stable `doc_id`. |
| **prediction** | `{pid}/predictions/_draft/{doc_id}.json` + experiment dirs | "prediction" in review-mode tab cards | Model output on a doc for the active or an experiment (prompt × model). Not ground truth. |
| **reviewed** | `{pid}/reviewed/{doc_id}.json` | docs/ row `reviewed` stamp + the ✏ tab in review mode + `/reviewed/{doc_id}` API | The human-corrected ground truth for a doc. Save target of the review screen. |
| **prompt** | `{pid}/prompts/{prompt_id}.json` (`schema.json` = active prompt's editing copy) | `prompts/` spine group | One axis of A/B variation. Owns schema fields + descriptions + global_notes. |
| **model** | `{pid}/models/{model_id}.json` | `models/` spine group | One axis of A/B variation. provider + provider_model_id + params. |
| **experiment** | `{pid}/experiments/{ex_id}/` (`meta.json` + `predictions/*.json`) | `experiments/` spine group + tab cards in review mode | A `(prompt, model)` pairing with cached predictions and an eval score. |
| **version** | `{pid}/versions/v{n}.json` | `versions/` spine group | A frozen prompt at publish time. Served by `/v1/{pid}/extract`. |
| **job** | `{pid}/jobs/{job_id}.jsonl` | `JobProgressCard` in chat | A background task (currently: autoresearch). JSONL event stream + pause/resume. |
| **api key** | `_keys.json` (hashed) | one-time reveal modal after `/publish` | Per-project secret used to call the prod fast-path. Plaintext never persisted. |
| **chat** | `{pid}/chats/{chat_id}.jsonl` (+ `.meta.json`) | chat conv column | One agent thread. New chat = new `chat_id`; full history is replayed. |
| **eval / metrics** | `{pid}/metrics/eval_{ts}.json` | right-rail `metrics/` card + `EvalCard` in chat | precision / recall / f1 / coverage from comparing predictions against reviewed. |

## Verbs (canonical commands)

These are the verbs the chrome (buttons, slash menu, help copy) speaks. Stay
task-type-agnostic — never `extract` / `invoice` in chrome copy. Reserve
`extract` for content/help text and route names (`/v1/{pid}/extract`).

| Verb | Slash command | Meaning |
|---|---|---|
| **init** | `/init` | Bootstrap a project's schema (or first prompt) from one or more sample docs. |
| **run** | (drag/drop or chat-driven) | Run the active prompt × model over one or more docs → write a draft prediction. |
| **review** | (click a `docs/` row) | Open the doc + prediction in the split view, edit fields, save → `reviewed/`. |
| **tune** | `/improve` | AutoResearch loop: propose prompt tweaks, score, keep the winner as a candidate version. |
| **publish** | `/publish` | Freeze the active prompt to `versions/v{n+1}.json`, mint an API key. |
| **ingest** | (drag/drop into chat) | Add a doc to the project. |

## Boundary clarifications

These are pairs that historically caused naming drift; pin them down once.

- **review** (verb / mode / activity) — the act of checking a prediction and
  correcting it. The screen is called **review mode**.
- **reviewed** (adjective / noun) — the artifact: a doc whose ground truth is
  stored at `reviewed/{doc_id}.json`. The badge on a docs/ row reads
  `reviewed`. The editable tab in review mode is labeled `reviewed` (with a
  ✏ icon).
- Do **not** introduce `annotation` / `annotate` / `label` / `ground truth` as
  parallel UI vocabulary. Internal code symbols can keep `annotation` (e.g.
  `TabSpec.kind = 'annotation'`) — they're cheap to keep stable and never
  user-visible.

- **prediction** vs **extract** — `prediction` is the artifact (one model run
  on one doc); `extract` is only the public API verb (`/v1/{pid}/extract`).
  Don't use `extract` as a noun in chrome.

- **prompt** vs **schema** — a prompt is the unit of variation; `schema.json`
  is just the editing copy of the **active** prompt's fields. There is no
  user-visible thing called "the schema" separate from "the active prompt".

- **doc** vs **document** — always `doc` in code and chrome. `document` is
  fine in long-form help copy if it reads better.

- **counterexample** — only used inside autoresearch; **never** rendered in
  runtime prompts and never surfaced as its own chrome term. The user calls
  these "notes" in the review screen.

- **fork** vs **import** — `fork` creates a new project; `import_prompt`
  copies a prompt across an existing fork relationship. Don't say "copy"
  for either in chrome.

## When this file should change

- Adding a new tracked object (e.g. introducing `runs/` or `comments/`):
  add a row, then ship the disk path + UI in matching names.
- Renaming an existing object: update the row, search-and-replace in chrome,
  and leave a note in `INSIGHTS.md` if the on-disk name has to stay for
  back-compat.
- Removing an object: strike the row and grep for stragglers.

## When it should NOT change

- Adding a per-feature tweak that already fits an existing term.
- Internal code symbols (`kind`, store keys, CSS classes) — they're free to
  diverge from chrome as long as the user-visible text follows the table.
