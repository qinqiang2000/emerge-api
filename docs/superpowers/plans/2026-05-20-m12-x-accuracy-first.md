# M12.x — accuracy-first metrics + matrix UI readability

> **Date:** 2026-05-20
> **Predecessor:** M12 (eval-as-module) shipped + dogfooded; M13 reverted
> **Trigger:** 2026-05-20 dogfood on `默沙东_小票` surfaced two real defects:
> 1. `invoice_code` field (zero ground-truth presence) shows F1=0 → drags macro by ~5.9pp; all "absent_both" cells deflate per-field accuracy across every rarely-present field (`remarks` worst hit).
> 2. Matrix page is unreadable when any cell has a large JSON array (`items`) — row height explodes, hides everything else.

## Goal

Replace F1/precision/recall headlines with **field accuracy** + **doc accuracy** (non-technical, non-engineer comprehensible). Make matrix page actually readable on real data.

## Hard rule

`absent_both` (model correctly predicted None when ground-truth was None) **counts as a correct prediction**. The model nailed it. Current scoring treats it as a non-event (excluded from F1 tp/fp/fn) and as a deflater for accuracy (counted in total, not in correct).

## Out of scope

- Inventing new metrics beyond accuracy. The user spec is "字段准确率 + 文档准确率" — keep it that simple.
- Per-field confidence dots / hallucination flags / latency reporting.
- Re-scoring historical eval directories. Old JSONs stay as snapshots; we render `accuracy` if present, fall back to deriving from `correct`+`total` if old shape.

## Phase A — scoring redesign

### T1 — Backend `app/eval/score.py::_aggregate`

- New accuracy formula: `accuracy = (correct + absent_both) / total` per field.
- Add `not_applicable: bool = True` when `total == 0` (corner case: schema has field but no entity ever exposes it — currently never happens, but defensive).
- Drop `precision/recall/f1/tp/fp/fn/support` computation from the hot path; emit nulls.
- New `field_accuracy_macro = mean(p.accuracy for p in per_field if not p.not_applicable)`.
- `doc_accuracy` unchanged — already counts `absent_both` as agreement (line 131 check).

### T2 — Backend `app/schemas/score.py`

`FieldScore`:
- Keep: `field`, `accuracy`
- Add: `correct: int`, `total: int`, `n_absent_both: int`, `not_applicable: bool = False`
- Demote to `Optional[None]` with default `None`: `tp, fp, fn, support, precision, recall, f1` (old shape readable, no longer authoritative)

`ScoreResultSummary`:
- Add: `field_accuracy_macro: float`
- Keep `macro_f1: float` as `Optional[None]` — only present on legacy eval reads, new writes emit `None`.

### T3 — Backend `app/tools/publish.py`

Readiness gate currently `macro_f1 < 0.7` (line 132, 173, 251, 281). Switch to **`field_accuracy_macro < 0.85`** (higher threshold since accuracy is a stricter measure than F1 — F1 penalty for false-negatives is lower than accuracy penalty for any disagreement). Update all 4 sites + the soft-warning band (currently `[0.7, 0.85)` → new `[0.85, 0.95)`).

### T4 — Backend `app/tools/experiment.py:335-341`

`ExperimentEval`:
- `score` → now stores `field_accuracy_macro` (the headline number for "is candidate better")
- `per_field: dict[str, float]` → values are accuracy, not f1
- `per_doc[fn] = single.field_accuracy_macro` (was `single.macro_f1`)

### T5 — Backend `app/api/routes/eval.py:108, 125`

The compare endpoint surfaces `macro_f1` for each eval. Switch to `field_accuracy_macro` (or both, for one release).

### T6 — Backend `app/tools/__init__.py:688`

Tool description "Compute precision/recall/F1/doc_accuracy" → "Compute field accuracy + doc accuracy".

## Phase B — frontend

### T7 — Types

`frontend/src/types/eval.ts` + `frontend/src/types/job.ts`:
- `FieldScoreSummary`: `{ field, accuracy, correct, total, n_absent_both, not_applicable }`
- Drop `precision, recall, f1` from new shape; allow optional for back-compat reads.
- `ScoreResult` / `ScoreResultSummary`: add `field_accuracy_macro`; deprecate `macro_f1` to optional.

### T8 — `Chat/EvalCard.tsx`

- Headline: `accuracy` (was `f1`) + `doc accuracy`. Drop P/R from the per-field table.
- Per-field rows: just `accuracy` + `n_absent_both` hint (e.g. "21/21 correct · 18 absent both sides").
- `not_applicable` rows render as `—` instead of red `0%`.

### T9 — `Context/ContextSurface.tsx:39-45`

Right rail "METRICS/" — replace `precision / recall / f1` items with `field accuracy / doc accuracy`. `coverage` stays.

### T10 — `stores/jobs.ts:70`

Best-turn picker: `data.macro_f1 > cur.bestTurn.macro_f1` → `data.field_accuracy_macro > cur.bestTurn.field_accuracy_macro`. Old-shape autoresearch turns (pre-M12.x) read `macro_f1` if `field_accuracy_macro` missing.

### T11 — `index.css:546`

`.eval-row .num.f1` → `.eval-row .num.acc`. Wherever the class is used in TSX, rename.

### T12 — Matrix page cell truncation

`frontend/src/components/Eval/MatrixCell.tsx` (or wherever the cell renders):
- `max-height: 96px` (~6 lines) + `overflow: hidden` + `text-overflow: ellipsis` (CSS) or visible truncation with `…`.
- On click: open a popover / sheet with the full content. Reuse `SchemaQuickLook`-style portal sheet if convenient; otherwise inline expandable.
- For arrays of objects (`items`): truncate the JSON.stringify to ~6 lines, append `… (n total)` with the array length.

### T13 — Matrix page column widths

Currently file column is huge. Set:
- `文件` column: 14ch (filename + hash) width, sticky-left
- Value cells: uniform 18ch min-width, wrap or truncate
- Headers: rotate 45° if too narrow? Or keep horizontal + tight font.

Use Excel/data-grid analog: rows = docs, columns = fields, cells = pred-vs-truth verdict. Compact, scannable.

## Phase C — back-compat read + tests

### T14 — Back-compat read

Anywhere the frontend reads an existing eval (M12 vintage) and `field_accuracy_macro` is missing, **synthesize on the fly**: `derived_macro = mean(p.f1 for p in per_field)` (still F1, marked stale via tooltip "legacy F1, not accuracy"). Better: on first read, run a tiny "lift" function backend-side: `GET /lab/projects/{slug}/eval/{ts}/summary?lift=accuracy` that recomputes accuracy from cells.jsonl (which has the per-cell verdicts intact). User gets correct numbers without re-running extract.

Decision point: implement the lift endpoint or stick with the simple `mean(f1)` synthesis for legacy? **Lift endpoint** is the SSU win — historical evals get real accuracy numbers, no re-extract needed. ~30 LOC backend.

### T15 — Tests

Update all asserts targeting `macro_f1` and per-field `f1/precision/recall`:
- `backend/tests/**/test_*eval*.py` — switch to `field_accuracy_macro` + per-field `accuracy`.
- `backend/tests/**/test_publish*.py` — switch gate to accuracy threshold.
- `frontend/__tests__/EvalCard*` — switch fixtures.
- One new test: `test_accuracy_counts_absent_both` — assert a field with all `absent_both` cells reports accuracy=1.0, not 0.0.

### T16 — Skill markdown updates

- `app/skills/emerge_extractor.md` — anywhere it explains "macro_f1" to the agent, switch to "field accuracy".
- `app/skills/emerge_publish.md` — readiness threshold reference.
- `app/skills/emerge_autoresearch.md` — best-turn comparison wording.

## Test footprint

Estimate: ~15-25 test files touched. Mostly mechanical renames + one new test asserting absent_both → accuracy=1.0.

## Hard rules respected

- Doc vision is pulled, not pushed — unchanged. ✅
- No image few-shot — unchanged. ✅
- `reviewed/` is ground truth, read-only by score — unchanged. ✅
- Publish fast-path 0 改动 (`/v1/{pid}/extract` route) — unchanged, only the readiness gate threshold + metric name change. ✅
- Agent brain ↔ Extract LLM separation — unchanged. ✅

## Acceptance

- Dogfood `默沙东_小票` post-M12.x:
  - `invoice_code` field accuracy = 100% (was F1 = 0.00)
  - `remarks` field accuracy noticeably higher (~14 of 24 "wrong" were absent_both → now counted correct)
  - Headline `field_accuracy_macro` for flash-2.5 should jump from 0.601 (old macro_f1) to ~0.70-0.75
  - Matrix page renders with all 21 doc rows visible at once; clicking `items` cell shows full JSON in popover
- No regression in publish flow: readiness still gates properly on the new threshold
- No regression in autoresearch best-turn pick: candidates with higher accuracy win

## Demo line

> 评估指标改成非技术人员可读的"字段准确率 + 文档准确率"，去掉 F1/P/R。把 `absent_both`（GT 和 pred 都为 None）正确计为模型预测正确，而不是被算法吃掉。`invoice_code` 这类餐饮票永远空的字段从 0.00 红字变成 100% 绿字。
