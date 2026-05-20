# M12.x.c — doc_accuracy smoothing + scalar-only sibling

> **Date:** 2026-05-20
> **Predecessor:** M12.x.b (normalize improvements, 0 lift but committed as insurance)
> **Trigger:** dogfood on `默沙东_小票` revealed `doc_accuracy = 4.8%` despite `field_accuracy_macro = 77%`. With 17 fields × multi-entity, one wrong cell → whole doc fails. The strict "all cells correct" definition has a theoretical ceiling of `0.95^17 ≈ 42%` even at 95% per-field accuracy. **The metric isn't measuring model quality — it's measuring brittleness.**

## Goal

Replace the brittle "doc_accuracy = % of docs with all cells correct" with a smooth per-doc accuracy mean. Add a sibling that excludes `array<*>` fields so weakness in one heavy array field (e.g. `items` with many sub-fields) doesn't dominate the doc-level signal.

## Spec

### New `doc_accuracy` (default headline, smooth)

```
doc_accuracy = mean over docs of: (correct_cells_in_doc + absent_both_cells_in_doc) / total_cells_in_doc
```

- Smooth in [0, 1]. No threshold. Each doc contributes its own field-accuracy to the average.
- Same numerator semantics as `field_accuracy_macro` (count `absent_both` as correct, M12.x rule).
- Difference vs `field_accuracy_macro`: that one averages over **fields** then over docs. This one averages over **docs**, giving each doc equal weight regardless of field count.

### New `doc_accuracy_without_array` (scalar-only sibling)

Same formula as `doc_accuracy` but **drop cells where the schema field has `type == ARRAY`**. The `items` array field's brittleness (length-mismatch, sub-field name fuzz) is filtered out — clean signal on header fields (seller_name, amounts, dates).

### Legacy `doc_accuracy_strict` (deprecated, optional)

Keep the old strict definition under a new key `doc_accuracy_strict` (Optional, default None). Useful for "is this doc 100% perfect?" signal. Backend writes both; frontend headlines the new `doc_accuracy`; legacy reads of old summary.json (where only `doc_accuracy` strict existed) still parse via pydantic default + frontend synth.

## Hard rules

- M12.x.b just shipped — `field_accuracy_macro` is the load-bearing field-level number. Don't change its semantics.
- Don't break the publish gate (`field_accuracy_macro ≥ 0.75` from M12.x). `doc_accuracy` is informational only, not a gate.
- Old eval directories (cells.jsonl) need to be readable; recompute new shape on demand from cells.

## Tasks

### T1 — Backend `_aggregate`

`backend/app/eval/score.py::_aggregate` — at the bottom, replace the current doc_correct loop with:

```python
# strict: legacy "all cells correct/absent_both"
doc_strict = sum(
    1 for fn, c_list in docs_seen.items()
    if fn in reviewed and all(c.status in ("correct", "absent_both") for c in c_list)
)
doc_accuracy_strict = doc_strict / n_reviewed_graded if n_reviewed_graded > 0 else 0.0

# smooth: mean over docs of (correct+absent_both)/total per doc
def _ok(c): return c.status in ("correct", "absent_both")
graded_docs = [c_list for fn, c_list in docs_seen.items() if fn in reviewed]
if graded_docs:
    doc_accuracy = sum(
        sum(1 for c in cs if _ok(c)) / len(cs)
        for cs in graded_docs
    ) / len(graded_docs)
else:
    doc_accuracy = 0.0

# without_array: same as smooth but skip cells where field.type == ARRAY
array_field_names = {f.name for f in schema if f.type == FieldType.ARRAY}
def _is_scalar(c): return c.field not in array_field_names
scalar_docs = []
for cs in graded_docs:
    scalar = [c for c in cs if _is_scalar(c)]
    if scalar:
        scalar_docs.append(scalar)
if scalar_docs:
    doc_accuracy_without_array = sum(
        sum(1 for c in cs if _ok(c)) / len(cs)
        for cs in scalar_docs
    ) / len(scalar_docs)
else:
    doc_accuracy_without_array = doc_accuracy  # no array fields in schema → identical
```

Return triple → quadruple from `_aggregate`. Update callers (only `score()` at line 267).

Import `FieldType` from `app.schemas.schema_field` at top if not already.

### T2 — `ScoreResultSummary` schema

`backend/app/schemas/score.py`:

```python
class ScoreResultSummary(BaseModel):
    ...
    doc_accuracy: Optional[float] = None              # smooth, M12.x.c (was strict pre-M12.x.c)
    doc_accuracy_without_array: Optional[float] = None  # NEW
    doc_accuracy_strict: Optional[float] = None        # NEW (legacy semantics, deprecated)
    ...
```

Keep `doc_accuracy` semantics SOFT — pydantic Optional means old summary.json with the strict value still parses. The frontend interprets `doc_accuracy` as smooth from the next score onward (M12.x.c eval directories), strict for legacy directories. The `doc_accuracy_strict` field is the disambiguator going forward: when present, frontend knows the `doc_accuracy` value is the new smooth definition.

### T3 — Tests

`backend/tests/unit/test_eval_score.py` — add:

- `test_doc_accuracy_smooth_vs_strict`: doc with 16/17 fields correct → strict=0/1=0.0 but smooth=16/17≈0.94. Assert both.
- `test_doc_accuracy_without_array`: schema has 1 array field + 4 scalars. One doc: array=wrong, 4 scalars=correct. `doc_accuracy`=4/5=0.80, `doc_accuracy_without_array`=4/4=1.00.
- `test_doc_accuracy_strict_legacy`: keep the existing strict-style test, just point it at `doc_accuracy_strict` (renamed key).

### T4 — Frontend

`frontend/src/types/eval.ts`:
- Add `doc_accuracy_without_array?: number` and `doc_accuracy_strict?: number` to `ScoreResult`.
- Existing `doc_accuracy?: number` stays (semantics shift quietly per backend write).

`frontend/src/components/Chat/EvalCard.tsx`:
- Headline shows `doc_accuracy` (smooth) as 文档准确率. If `doc_accuracy_without_array` is materially different (Δ ≥ 0.05), show as small parenthetical: `(去除 items：N%)`.
- Don't surface `doc_accuracy_strict` in chat — too brittle for stakeholder reading.

`frontend/src/components/Context/ContextSurface.tsx`:
- Right-rail metrics: 字段准确率 / 文档准确率 / coverage. If `doc_accuracy_without_array` present and meaningfully different, swap "文档准确率" line for two: 文档准确率 (整体) + 文档准确率 (去除 items).

`frontend/src/components/EvalMatrix/EvalMatrixPage.tsx`:
- Top-right summary: show all three numbers if backend wrote them: 字段准确率 / 文档准确率 / 文档准确率 (去除 items). Strict version optional via hover or "advanced" toggle.

### T5 — Live verify on `默沙东_小票`

After T1-T4 land, run:
```python
import json, urllib.request, urllib.parse
slug = urllib.parse.quote("默沙东_小票", safe="")
body = json.dumps({}).encode()
req = urllib.request.Request(f"http://localhost:8080/lab/projects/{slug}/score", data=body, headers={"Content-Type":"application/json"}, method="POST")
out = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
print(f"field_accuracy_macro:        {out['field_accuracy_macro']:.4f}")
print(f"doc_accuracy (smooth):       {out['doc_accuracy']:.4f}")
print(f"doc_accuracy_without_array:  {out['doc_accuracy_without_array']:.4f}")
print(f"doc_accuracy_strict (legacy):{out['doc_accuracy_strict']:.4f}")
```

Expected:
- `doc_accuracy` (smooth) ≈ 0.77 (close to field_accuracy_macro since both are means over the same cells, just different averaging order)
- `doc_accuracy_without_array` likely ≥ 0.85 (items is the worst field; removing it cleans the signal)
- `doc_accuracy_strict` = 0.0476 (unchanged — legacy definition)

### T6 — ROADMAP

Append M12.x.c row after M12.x.b in `docs/superpowers/plans/ROADMAP.md`. Match neighboring style. Include the 3-number readout from T5.

## Skip-checklist

- Don't change `field_accuracy_macro` semantics — that's the M12.x contract.
- Don't change the publish gate threshold.
- Don't touch the matrix grid UI (cells/rows).
- Don't add a 4th doc-accuracy variant — three is the cap.
- Don't synthesize `doc_accuracy_without_array` for legacy eval directories — leave as null. Frontend renders `—` if missing.

## Acceptance

- Backend tests pass (~1010 + 3 new)
- Frontend tests pass (462 + 0 changes expected, types just gain optional fields)
- Live `默沙东_小票`: `doc_accuracy` jumps from 4.8% → ~77% (the smooth number); `doc_accuracy_without_array` ≥ 85%
- Demo: "文档准确率 4.8%" gone. Stakeholder sees ~77% and a parenthetical ~85% (sans items) — non-misleading.

## Demo line

> 文档准确率从严格的"全字段无错"放宽成"每 doc 字段准确率平均"，更贴近 stakeholder 直觉。再加一个"去除 items 字段"的版本，把数组类型字段（最脆）单独剥离。`默沙东_小票`：文档准确率从误导性的 4.8% 提升到真实的 ~77%（去除 items 约 ~85%）。
