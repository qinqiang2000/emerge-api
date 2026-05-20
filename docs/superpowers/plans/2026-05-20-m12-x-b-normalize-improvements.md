# M12.x.b — normalize-judge improvements (array-of-object + fullwidth)

> **Date:** 2026-05-20
> **Predecessor:** M12.x (accuracy-first metrics) just shipped
> **Trigger:** dogfood revealed `doc_accuracy = 4.8%` on `默沙东_小票`. Per-cell forensic on 18 wrong cells from 10 "near-perfect" docs found:
> - **~50% of wrong cells are `items` array where pred has `1.0` and truth has `1`** (or vice versa). Same value, different JSON serialization. The L2 normalize layer compares `str(list)` and bails before any per-item rule applies.
> - **~10% are CJK fullwidth vs halfwidth punctuation** (`，！` vs `,!`). NFC normalization (current) doesn't compress those; NFKC does.

## Goal

Make `normalize_equivalent` handle two structural cases the current code can't:

1. **Array-of-object fields** (e.g. `items: list[{name, quantity, unit_price, amount}]`) — decompose both sides into Python lists, walk per item, compare each sub-scalar with the existing normalize rules.
2. **CJK fullwidth punctuation** — switch `_unicode_canonical` from NFC to NFKC, OR add an explicit fullwidth-to-halfwidth pass.

Acceptance: `默沙东_小票` doc_accuracy jumps from 4.8% to ~20-30%; field_accuracy_macro lifts from 77% to ~83-87%. No regression in scalar-field accuracy.

## Hard rule

`normalize_equivalent` is a **read-side scoring function**. It must NOT mutate cell verdicts already on disk (`cells.jsonl`), only future scores. To verify a fix improved scoring, re-run `/score` (which rebuilds cells.jsonl from `_draft/` + `reviewed/`).

## Out of scope

- GT cleanup (seller_name branch-suffix policy on `默沙东_小票`) — that's a human curation task, not code.
- Schema description tweaks (e.g. "include 套餐 sub-items in items array") — also project-specific curation.
- Cross-language Thai/EN handling for `02ba18df.pdf` outlier — single doc, separate decision.
- L3 LLM-judge improvements — distinct M12.x.c candidate if dogfood demands.

## Tasks

### T1 — `_unicode_canonical` switch NFC → NFKC

`backend/app/eval/normalize.py:25-28`:

```python
def _unicode_canonical(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)  # was "NFC"
    s = _WS.sub(" ", s.strip())
    return s
```

NFKC includes the "compatibility" decomposition step (e.g. fullwidth `，` → halfwidth `,`, fullwidth digit `１` → ASCII `1`). It's strictly more aggressive than NFC; risk surface is minimal for receipt-extraction context.

Add unit test: `"，！" → "," + "!"` after canonical; `"半天妖（济南店）" → "半天妖(济南店)"`.

### T2 — Array-of-object structural compare

`backend/app/eval/normalize.py::normalize_equivalent` — when `field.type == FieldType.ARRAY`, before falling through to fuzz.ratio:

1. Try to parse both `truth` and `pred` strings as Python literals via `ast.literal_eval`. If either fails: skip this branch.
2. If both parse to `list`: check length equal. If unequal: not equivalent (don't fuzz; arrays of different lengths are genuinely different).
3. If `field.items.type == FieldType.OBJECT`: for each (truth_item, pred_item) pair:
   - Both should be `dict`. If not: not equivalent.
   - For each sub-field in `field.items.properties`:
     - Pull values from truth_item and pred_item (default None if key missing).
     - Recursively call `normalize_equivalent(t_val, p_val, sub_field)`.
     - If not equivalent: bail.
4. If `field.items.type` is a scalar (string/number/etc.): pairwise compare via `normalize_equivalent` with `field.items` as the scalar sub-field.
5. All items pass → `NormalizeResult(True, "array")`.

**Edge case**: `truth_v = None and pred_v = None` (sub-field both absent) → equivalent. This already matches what `absent_both` does at the cell level; we're replicating the same logic at the sub-cell level.

**Edge case**: empty string `""` and `None` for sub-fields — treat as equivalent (per user hypothesis). Add a `_loose_absent(v)` helper: `v is None or v == ""` → True.

### T3 — Tests

New unit tests in `backend/tests/unit/test_eval_normalize.py` (or wherever existing normalize tests live):

- `test_normalize_array_int_vs_float`: `[{'q': 1}]` vs `[{'q': 1.0}]` → equivalent, normalizer="array"
- `test_normalize_array_unicode_punct`: `[{'name': '半天妖（济南）'}]` vs `[{'name': '半天妖(济南)'}]` → equivalent
- `test_normalize_array_length_mismatch`: `[{'q': 1}]` vs `[{'q': 1}, {'q': 2}]` → NOT equivalent
- `test_normalize_array_empty_vs_none_subfield`: `[{'unit_price': None}]` vs `[{'unit_price': ''}]` → equivalent
- `test_normalize_fullwidth_punct`: `"a，b！c"` vs `"a,b!c"` → equivalent at scalar level (via NFKC)
- `test_normalize_array_real_dogfood_case`: copy-paste one of the actual `default沙东_小票` items rows from `cells.jsonl` (e.g. the 0034f6ca.jpg one with quantity 1.0 vs 1) → equivalent

Aim for ~6 new tests. Existing tests should all still pass — the change is additive.

### T4 — Re-score `默沙东_小票` to measure lift

After T1-T3 land:
```python
import json, urllib.request, urllib.parse
slug = urllib.parse.quote("默沙东_小票", safe="")
body = json.dumps({}).encode()
req = urllib.request.Request(f"http://localhost:8080/lab/projects/{slug}/score", data=body, headers={"Content-Type":"application/json"}, method="POST")
out = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
print(f"field_accuracy_macro: {out['field_accuracy_macro']:.4f}")
print(f"doc_accuracy:         {out['doc_accuracy']:.4f}")
```

Expected:
- `field_accuracy_macro` from 0.770 → 0.83-0.87
- `doc_accuracy` from 0.048 → 0.20-0.40 (depends how many docs still have non-normalize errors)

If doc_accuracy still <0.15 after the fix, investigate what's still wrong (sample wrong cells again).

### T5 — ROADMAP closeout

Append M12.x.b row to ROADMAP after M12.x.

## Hard rules respected

- Doc vision pulled not pushed — unchanged. ✅
- No image few-shot — unchanged. ✅
- Cells stored on disk are immutable — only future scores get the new normalize. ✅
- F1/precision/recall already removed in M12.x — accuracy stays the headline. ✅

## Test footprint

- ~6 new tests (test_eval_normalize)
- 0 expected updates to existing tests (additive change)
- 0 frontend changes (this is purely backend scoring math)
- 0 schema/route changes

## Skip-checklist (do not do)

- Don't change `cells.jsonl` shape or serialization — read-side only.
- Don't change `FieldScore` schema — already accuracy-first from M12.x.
- Don't introduce array-of-array or array-of-array-of-object handling — schema doesn't use those.
- Don't recurse beyond 2 levels (array.items.object.properties.field) — that's all the schema supports today.

## Demo line

> 评分逻辑能识别 `1` 和 `1.0` 是同一个数字、能识别全角逗号和半角逗号是同一个符号了。`默沙东_小票` 字段准确率从 77% 提到 X%，文档准确率从 4.8% 提到 Y%。
