# M12 — Eval as a module (per-cell matrix + L1/L2/L3 verdicts + UI)

> **For agentic workers:** execute task-by-task. Each task is self-contained
> (files + code sketch + test command + commit message). Run the test step
> at the end of every task; commit only when green. Stop and report on
> repeated failures. **Do not ask for direction between tasks**—every
> design decision is locked in below. Only stop if a task's acceptance
> criteria can't be met for technical reasons (e.g. library API surprise).

**Goal:** turn extraction eval from "one number" into "a folder of files."
The on-disk eval artifact becomes the source of truth — readable by agent
(via `Bash cat … | jq`), by Excel (via `matrix.csv`), and by a new frontend
matrix page. Field-value equivalence is decided by a three-layer verdict
pipeline (Normalize → optional LLM-judge → Presence-policy) so "123.10"
== "123.1", `{a:1,b:null}` == `{a:1}` (under default policy), and
"广东省深圳市" == "广东省 深圳市" all stop counting as errors.

**Why now**: M9.x landed the (prompt × model) axes and experiment tabs.
The bottleneck is now eval credibility — current `score._eq()` is a bare
`str().strip()` compare so reported macro_f1 systematically underestimates
real accuracy on number/date/whitespace-divergent fields. Without
credible eval, /compare across models (M12.7) is a noisy signal and
customers won't trust a "92%" number to make migration decisions. This
milestone fixes the credibility hole and ships the customer-visible
artifact (per-doc per-field matrix) that converts "92%" from a claim
into something verifiable.

**Architecture (one picture):**

```
                    reviewed/*.json
                         │
                         ▼
              ┌────────────────────────┐
              │  eval/score.py         │
              │  orchestrator          │
              └────────┬───────────────┘
                       │ for each (filename, entity_idx, field):
                       ▼
              ┌────────────────────────┐
              │  Pipeline              │
              │   ┌─────────────┐      │
              │   │ presence    │ L3   │  decide: is one/both absent?
              │   │ (policy)    │      │
              │   └──┬──────────┘      │
              │      ▼                 │
              │   ┌─────────────┐      │
              │   │ normalize   │ L1   │  canonicalize per field type:
              │   │ (type-      │      │   number / date / money /
              │   │  dispatch)  │      │   string-fuzzy / enum
              │   └──┬──────────┘      │
              │      ▼                 │
              │   ┌─────────────┐      │
              │   │ llm_judge   │ L2   │  optional (opt-in via param)
              │   │ (cached,    │      │   gemini-flash-lite-latest
              │   │  batched)   │      │   only on L1-disagreements
              │   └──┬──────────┘      │
              └──────┼─────────────────┘
                     ▼
              CellVerdict
                     │
                     ▼
        metrics/eval_<ts>/
          ├── summary.json    aggregates (macro_f1, doc_accuracy, per_field…)
          ├── cells.jsonl     per-cell ground truth (one row per cell)
          ├── matrix.csv      pivot for human/Excel; <field>·truth, <field>·pred
          └── meta.json       prompt_id, model_id, judge_used, ts, scope
```

predictions are read from `predictions/_draft/*.json` for `run_eval` (active
config baseline) and from `experiments/<exp_id>/predictions/*.json` for
`run_experiment_eval` (candidate). Both feed the same pipeline.

**Tech stack:** FastAPI + pydantic v2 + uv (backend) — adds three pip deps:
`rapidfuzz`, `dateparser`, `Babel`. React 19 + Zustand + react-router 6
(frontend) — adds one new route `/projects/:slug/eval/:ts` and one
sub-route `/projects/:slug/eval/compare`. Backend test:
`cd backend && uv run pytest <path> -v`. Frontend test:
`cd frontend && npm test -- <pattern>` and `npx tsc --noEmit`.

**Reference docs:**
- Predecessor surface: M9.3 (experiments + review tabs), M11 (tool↔HTTP symmetry)
- INSIGHTS to respect: #1/#1.5 (workspace safety gate), #4 (Gemini schema)
- CLAUDE.md hard rules: no image few-shot, no bbox, public API reads `versions/v<n>.json` (untouched), `schema.json` only via `write_schema` (untouched). M12 only adds new files under `metrics/eval_<ts>/` and `.eval_judge_cache/`; no existing artifacts mutate.

**Locked design decisions (no mid-stream Q):**

1. **Disk shape**: `metrics/eval_<ts>/` is a **directory**, not a JSON file. Legacy `metrics/eval_<ts>.json` files keep working via lazy migration on read.
2. **`cells.jsonl` line schema (frozen)**:
   ```json
   {"filename":"INV-001.pdf","entity_idx":0,"field":"tax_id",
    "status":"wrong|correct|missing|spurious|absent_both",
    "truth":"123.10","pred":"123.1",
    "verdict_source":"exact|normalize|llm_judge|presence",
    "judge_reason":null,"judge_model":null,
    "normalizer":"number"}
   ```
3. **`summary.json` schema** = `ScoreResultSummary` pydantic (new) = old `ScoreResult` fields + `doc_accuracy: float` + `per_field[*].accuracy: float` + `judge_used: int` + `judge_skipped_budget: int`. `per_cell` is NOT in summary.json (size).
4. **`matrix.csv` layout**: `filename, entity_idx, n_fields_correct, <field1>·truth, <field1>·pred, <field2>·truth, <field2>·pred, ...`. Schema declaration order. Separator U+00B7 (`·`). Absent values render as empty string.
5. **`meta.json`**: `{"prompt_id": "...", "model_id": "...", "experiment_id": null|"ex_...", "judge_used": 0, "judge_skipped_budget": 0, "ts": "...", "schema_field_count": N, "n_reviewed": N}`.
6. **L1 normalize coverage (frozen order, all in M12.2)**:
   - `unicode` (NFC + strip + collapse `\s+` → ` `) — applied to every string-typed pair first.
   - `number` — parse via `Decimal`, strip trailing zeros, comma-thousands. Falls back to string compare if either side doesn't parse.
   - `date` — `dateparser.parse` with `DATE_ORDER=YMD` default. Per-field `date_order` schema attr can override.
   - `money` — try `babel.numbers.parse_decimal` per common locale (en_US, en_GB, de_DE, zh_CN); compare numerical equivalence. Currency code optional sidecar.
   - `string` — after unicode, apply `rapidfuzz.ratio` ≥ 95 = equivalent (configurable per field).
   - `enum` — case-fold + strip punctuation, then equality.
7. **Normalizer dispatch**: by `SchemaField.type`. If `type` missing on field, default to `string` (current schema default).
8. **L3 absent_policy**: per-field `absent_policy: Literal["lenient","strict"] = None` on `SchemaField`. `None` (= unset) inherits project default = `lenient`. `lenient` = `None | "" | "n/a" | "none" | "null"` (case-insensitive after strip) all absent. `strict` = only key-not-in-dict OR `None` is absent (empty string is "the model said empty, which is a present value").
9. **L2 LLM judge** (opt-in, off by default):
   - Triggered only via `use_llm_judge: bool = False` param on `score` tool and `POST /lab/projects/{slug}/eval`.
   - Model: env `EMERGE_LLM_JUDGE_MODEL`, default `gemini-flash-lite-latest`.
   - Provider: same `get_provider_for_model` path. **NOT** routed through Claude Agent SDK (red line: "tool body never recurses to SDK").
   - Budget: env `EMERGE_LLM_JUDGE_BUDGET_PER_EVAL`, default 200 cells/run. Over budget → remaining disagreements keep L1 verdict, `judge_skipped_budget` counter increments.
   - Cache: `{project}/.eval_judge_cache/<sha256(field_name|truth|pred)>.json`. Hash includes `field_name` so same `(rv, pv)` under different field can produce different verdicts. Cache hits never re-judge.
   - Failure-graceful: judge HTTP error → fallback to L1 verdict, log error in `summary.json.errors[]`.
10. **Frontend routes**:
    - `/projects/:slug/eval/latest` — symlink-like, resolves to most-recent `metrics/eval_<ts>/`
    - `/projects/:slug/eval/:ts` — single eval matrix view
    - `/projects/:slug/eval/compare?a=<ts1>&b=<ts2>` — two-matrix diff
    Cell click → router push to review mode for that filename + focus the field. Reuses `ui_set_active_field`.
11. **`/compare` skill (chat-side)**:
    - Triggered by `/compare <model_id>` or NL "对比 X / 试试 X 在我们数据上".
    - Sequence: probe reviewed count → write `models/m_xxx.json` if missing → `create_experiment` → `run_experiment_eval` → `score` (active baseline) → agent renders markdown delta + link to compare page.
    - Lives in `backend/app/skills/emerge_extractor.md` (route addition, not new skill).
12. **HTTP route symmetry**: each new tool gets a matching HTTP route under `/lab/projects/{slug}/...`. New `test_symmetry_invariant.py` entries added.
13. **`SchemaField` migration**: `absent_policy` is `Optional[Literal[...]] = None`. Old `prompts/{pid}.json` files load fine without it (default applies).
14. **Lazy legacy `metrics/eval_<ts>.json` read**: `get_eval_latest` checks `is_file()` vs `is_dir()`. Legacy file = wrap as `ScoreResultSummary` (no per_cell, no doc_accuracy). Frontend matrix page on legacy ts shows "this eval predates per-cell data" empty state.
15. **No backfill**: existing reviewed sets are NOT re-evaled at migration time. Next `/eval` produces the new dir form.

**Scope boundary — explicitly OUT of scope:**

- Evaluator-in-the-loop (per-cell override by user) — data model accommodates it (`verdict_source` field) but no UI/API surface this milestone.
- Schema-level eval policy editor in UI — `absent_policy` is set via direct `Edit prompts/{pid}.json` (or via `write_schema` future patch); no FieldEditor UI changes in M12.
- Multi-language `date_order` heuristics — single `date_order` per field; locale auto-detection from filename/content is out.
- Judge model selection UI — env-only this round. Project-level override TBD.
- Real-time matrix updates (streaming as `run_eval` runs) — `run_eval` is blocking, then matrix is fully written. Page polls or refresh.
- Frontend per-cell editor (override judge verdict from UI) — out.
- Cross-project eval diff — single-project this milestone; cross-project deferred.

---

## File map

**New files (backend):**

```
backend/app/eval/__init__.py
backend/app/eval/types.py          # CellVerdict, CellStatus, VerdictSource pydantic
backend/app/eval/presence.py       # L3 absent_policy resolver
backend/app/eval/normalize.py      # L1 type-dispatched canonicalizers
backend/app/eval/judge.py          # L2 LLM judge + cache
backend/app/eval/score.py          # orchestrator (moved from tools/score.py + per_cell)
backend/app/eval/pivot.py          # cells.jsonl → matrix.csv helper

backend/tests/unit/test_eval_presence.py
backend/tests/unit/test_eval_normalize.py
backend/tests/unit/test_eval_judge.py
backend/tests/unit/test_eval_score.py          # replaces test_score.py (renamed)
backend/tests/unit/test_eval_pivot.py
backend/tests/unit/test_eval_lazy_legacy_read.py
```

**Modified (backend):**

```
backend/app/tools/score.py                # thin re-export from eval/, keep tool name
backend/app/schemas/score.py              # add doc_accuracy, per_field.accuracy; rename ScoreResult → ScoreResultSummary (alias both names)
backend/app/schemas/schema_field.py       # add absent_policy: Optional[Literal["lenient","strict"]] = None
backend/app/api/routes/eval.py            # /eval and /score accept use_llm_judge; return summary; new /eval/<ts>/cells.jsonl GET, /eval/<ts>/matrix.csv GET, /eval/<ts>/summary.json GET
backend/app/api/routes/experiments.py     # run_experiment_eval accepts use_llm_judge param
backend/app/tools/__init__.py             # score tool param + run_experiment_eval param + tool descriptions
backend/app/workspace/paths.py            # add eval_dir(ws, slug, ts), eval_cells_path, eval_matrix_path, eval_summary_path, eval_meta_path, eval_judge_cache_dir, eval_judge_cache_path
backend/app/config.py                     # add llm_judge_model, llm_judge_budget_per_eval settings
backend/app/jobs/autoresearch.py          # touch read path so it tolerates dir-form metrics (still uses ScoreResultSummary)
backend/app/skills/emerge_extractor.md    # /compare skill route + reference to matrix page
backend/tests/unit/test_symmetry_invariant.py  # add new tool↔route entries
```

**Removed (backend):**

```
backend/tests/unit/test_score.py          # replaced by test_eval_score.py
backend/app/tools/score.py                # moved to eval/score.py (re-export kept for tools/__init__ binding compat)
```

**Modified (frontend):**

```
frontend/src/components/Chat/EvalCard.tsx      # add doc_accuracy in header, "open matrix →" link
frontend/src/components/EvalMatrix/             # NEW: matrix page + compare page + cell drilldown
  EvalMatrixPage.tsx
  EvalCompare.tsx
  MatrixGrid.tsx
  CellDrilldown.tsx
  filters.ts
frontend/src/lib/api.ts                         # eval matrix fetch helpers
frontend/src/stores/eval.ts                     # NEW: eval store (loads summary + cells + matrix per ts)
frontend/src/App.tsx                            # route registration
frontend/src/components/Spine/FSSpine.tsx       # metrics/ leaf click → route to /eval/<ts>
```

**New deps:**

```
backend/pyproject.toml: rapidfuzz>=3.0, dateparser>=1.2, Babel>=2.14
```

---

## Task 1 — Backend deps + paths helpers + eval/ skeleton

**Scope:** prepare disk layout helpers and module skeleton; nothing changes runtime behavior yet.

**Files:**

- `backend/pyproject.toml`: add `rapidfuzz`, `dateparser`, `Babel`
- `backend/app/workspace/paths.py`: add 7 path helpers
- `backend/app/eval/__init__.py`: empty placeholder
- `backend/app/eval/types.py`: pydantic models (CellVerdict, CellStatus, VerdictSource)
- `backend/app/config.py`: 2 new env-driven settings

**Code sketch (paths.py addition):**

```python
def eval_dir(workspace: Path, slug: str, ts: str) -> Path:
    return metrics_dir(workspace, slug) / f"eval_{ts}"

def eval_summary_path(workspace: Path, slug: str, ts: str) -> Path:
    return eval_dir(workspace, slug, ts) / "summary.json"

def eval_cells_path(workspace: Path, slug: str, ts: str) -> Path:
    return eval_dir(workspace, slug, ts) / "cells.jsonl"

def eval_matrix_path(workspace: Path, slug: str, ts: str) -> Path:
    return eval_dir(workspace, slug, ts) / "matrix.csv"

def eval_meta_path(workspace: Path, slug: str, ts: str) -> Path:
    return eval_dir(workspace, slug, ts) / "meta.json"

def eval_judge_cache_dir(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / ".eval_judge_cache"

def eval_judge_cache_path(workspace: Path, slug: str, sha256_hex: str) -> Path:
    return eval_judge_cache_dir(workspace, slug) / f"{sha256_hex}.json"
```

**Code sketch (types.py):**

```python
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict

CellStatus = Literal["correct", "wrong", "missing", "spurious", "absent_both"]
VerdictSource = Literal["exact", "normalize", "llm_judge", "presence"]

class CellVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str
    entity_idx: int
    field: str
    status: CellStatus
    truth: Optional[str] = None       # stringified for jsonl portability
    pred: Optional[str] = None
    verdict_source: VerdictSource
    normalizer: Optional[str] = None  # which L1 normalizer fired, if any
    judge_reason: Optional[str] = None
    judge_model: Optional[str] = None
```

**Code sketch (config.py addition to Settings class):**

```python
llm_judge_model: str = "gemini-flash-lite-latest"
llm_judge_budget_per_eval: int = 200
```

**Test:** `cd backend && uv run pytest backend/tests/unit/test_eval_paths.py -v` (new test file: assert path helpers return expected paths; assert CellVerdict round-trips).

**Acceptance:**
- `uv sync` succeeds, new deps install
- `from app.eval.types import CellVerdict, CellStatus, VerdictSource` works
- existing `pytest backend/tests/unit/ -v` still green (no regressions)

**Commit message:** `feat(m12-t1): eval/ module skeleton + paths helpers + new deps`

---

## Task 2 — Schema additions: ScoreResultSummary, FieldScore.accuracy, doc_accuracy, SchemaField.absent_policy

**Scope:** widen pydantic models to carry per-cell-derived aggregates and per-field policy. Backward compatible (all new fields Optional or have safe defaults).

**Files:**

- `backend/app/schemas/score.py`: add `accuracy`, `doc_accuracy`, `judge_used`, `judge_skipped_budget`; introduce `ScoreResultSummary` (= renamed `ScoreResult`); keep `ScoreResult` as alias for back-compat imports.
- `backend/app/schemas/schema_field.py`: add `absent_policy: Optional[Literal["lenient","strict"]] = None`

**Code sketch (score.py):**

```python
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict

class FieldScore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    tp: int
    fp: int
    fn: int
    support: int
    precision: float
    recall: float
    f1: float
    accuracy: Optional[float] = None      # NEW: entity-level correct/total

class ScoreResultSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n_docs: int
    n_reviewed: int
    macro_f1: float
    doc_accuracy: Optional[float] = None  # NEW: docs fully correct / n_reviewed
    per_field: list[FieldScore]
    errors: list[str]
    ts: str
    schema_field_count: int
    judge_used: int = 0                    # NEW: # cells LLM-judged
    judge_skipped_budget: int = 0          # NEW: # disagreements not judged due to budget

# Back-compat alias: existing imports of ScoreResult keep working
ScoreResult = ScoreResultSummary
```

**Code sketch (schema_field.py addition):**

```python
absent_policy: Optional[Literal["lenient", "strict"]] = None
```

**Test:**
- `pytest backend/tests/unit/test_score.py -v` (existing) — pass with `Optional` defaults
- `pytest backend/tests/unit/test_schema.py -v` (existing) — old prompts/*.json still parse

**Acceptance:**
- existing `ScoreResult(**old_blob)` works (Optional + defaults)
- new fields appear in `.model_dump()` of new evals
- `SchemaField` parses old prompts/*.json without `absent_policy`
- existing tests all green

**Commit message:** `feat(m12-t2): widen score + schema_field models with accuracy/doc_accuracy/absent_policy`

---

## Task 3 — L3 presence module + tests

**Scope:** explicit absent_policy resolver, separated from `_absent()` heuristic.

**Files:**

- `backend/app/eval/presence.py` (new)
- `backend/tests/unit/test_eval_presence.py` (new)

**Code sketch:**

```python
from typing import Any, Literal, Optional
from app.schemas.schema_field import SchemaField

AbsentPolicy = Literal["lenient", "strict"]
DEFAULT_PROJECT_POLICY: AbsentPolicy = "lenient"
LENIENT_ABSENT_LITERALS = frozenset({"", "n/a", "none", "null"})

def resolve_policy(field: SchemaField, project_default: AbsentPolicy = DEFAULT_PROJECT_POLICY) -> AbsentPolicy:
    return field.absent_policy or project_default

def is_absent(value: Any, policy: AbsentPolicy) -> bool:
    if value is None:
        return True
    if policy == "strict":
        return False  # only None or missing-key counts; the missing-key
                       # case is handled by dict.get returning None upstream
    if isinstance(value, str):
        return value.strip().lower() in LENIENT_ABSENT_LITERALS
    return False
```

**Test cases (test_eval_presence.py):**

- `is_absent(None, "lenient") == True`
- `is_absent(None, "strict") == True`
- `is_absent("", "lenient") == True`
- `is_absent("", "strict") == False`  ← key behavioral difference
- `is_absent("  N/A  ", "lenient") == True`
- `is_absent("  N/A  ", "strict") == False`
- `is_absent("0", "lenient") == False`  ← guardrail: "0" is a value
- `is_absent(0, "lenient") == False`
- `resolve_policy(SchemaField(name="x", type="string", description="..."), "lenient") == "lenient"`
- `resolve_policy(SchemaField(name="x", absent_policy="strict", ...), "lenient") == "strict"`

**Test:** `cd backend && uv run pytest backend/tests/unit/test_eval_presence.py -v`

**Acceptance:** all 10 cases pass; coverage of `presence.py` ≥ 95% lines.

**Commit message:** `feat(m12-t3): eval.presence — absent_policy resolver (lenient default + strict opt-in)`

---

## Task 4 — L1 normalize module + per-type tests

**Scope:** type-dispatched canonicalizers using rapidfuzz / dateparser / Babel. Field type pulled from `SchemaField.type`.

**Files:**

- `backend/app/eval/normalize.py` (new)
- `backend/tests/unit/test_eval_normalize.py` (new)

**Code sketch:**

```python
import unicodedata
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, NamedTuple

from rapidfuzz.distance import Levenshtein
from rapidfuzz import fuzz
import dateparser
from babel.numbers import parse_decimal, NumberFormatError

from app.schemas.schema_field import SchemaField


class NormalizeResult(NamedTuple):
    equivalent: bool
    normalizer: Optional[str]  # name of the normalizer that fired


_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)
_NUMBER_LOCALES = ("en_US", "en_GB", "de_DE", "zh_CN")


def _unicode_canonical(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = _WS.sub(" ", s.strip())
    return s


def _try_number(s: str) -> Optional[Decimal]:
    # Try plain Decimal first
    cleaned = s.replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        pass
    # Try Babel locales
    for loc in _NUMBER_LOCALES:
        try:
            return Decimal(parse_decimal(s, locale=loc))
        except (NumberFormatError, InvalidOperation):
            continue
    return None


def _try_date(s: str, date_order: str = "YMD"):
    return dateparser.parse(s, settings={"DATE_ORDER": date_order})


def normalize_equivalent(
    truth: Any,
    pred: Any,
    field: SchemaField,
) -> NormalizeResult:
    """Return (equivalent, which_normalizer_fired) for a non-absent pair.
    Caller has already established neither side is absent."""
    if truth is None or pred is None:
        return NormalizeResult(False, None)

    t = str(truth)
    p = str(pred)

    # Step 0: exact string equality before normalization
    if t == p:
        return NormalizeResult(True, None)  # "exact" upstream

    # Step 1: unicode canonical for any string-bearing type
    t_u = _unicode_canonical(t)
    p_u = _unicode_canonical(p)
    if t_u == p_u:
        return NormalizeResult(True, "unicode")

    field_type = (field.type or "string").lower()

    # Step 2: numbers
    if field_type in ("number", "integer", "decimal", "float"):
        td, pd_ = _try_number(t_u), _try_number(p_u)
        if td is not None and pd_ is not None and td == pd_:
            return NormalizeResult(True, "number")

    # Step 3: dates
    if field_type in ("date", "datetime"):
        order = getattr(field, "date_order", None) or "YMD"
        td_, pd_ = _try_date(t_u, order), _try_date(p_u, order)
        if td_ is not None and pd_ is not None and td_.date() == pd_.date():
            return NormalizeResult(True, "date")

    # Step 4: money — try number first (locale-aware), then ignore currency code
    if field_type in ("money", "currency", "amount"):
        # Strip currency symbols/codes
        t_strip = re.sub(r"[^\d.,\-]", "", t_u)
        p_strip = re.sub(r"[^\d.,\-]", "", p_u)
        td, pd_ = _try_number(t_strip), _try_number(p_strip)
        if td is not None and pd_ is not None and td == pd_:
            return NormalizeResult(True, "money")

    # Step 5: enum / id-like — strip punctuation, casefold
    if field_type in ("enum", "id", "code"):
        t_canon = _PUNCT.sub("", t_u).casefold()
        p_canon = _PUNCT.sub("", p_u).casefold()
        if t_canon == p_canon:
            return NormalizeResult(True, "enum")

    # Step 6: string fuzzy (default for "string" type and fallback)
    threshold = getattr(field, "fuzzy_threshold", None) or 95
    if fuzz.ratio(t_u, p_u) >= threshold:
        return NormalizeResult(True, "string-fuzzy")

    return NormalizeResult(False, None)
```

**Test cases (test_eval_normalize.py):**

For each normalizer, 3-4 positives + 2-3 negatives:

```python
# number
("123.10", "123.1", "number", True)
("1,000", "1000", "number", True)
("$1,000.00", "1000", "money", True)
("100", "100.01", "number", False)

# date
("2024/3/12", "2024-03-12", "date", True)
("12 March 2024", "2024-03-12", "date", True)
("2024-03-12", "2024-03-13", "date", False)

# unicode/whitespace
("广东省深圳市", "广东省 深圳市", "string", True)  # via unicode + fuzzy fallback
("ACME  Sdn  Bhd", "ACME Sdn Bhd", "string", True)

# enum
("INV-001", "inv001", "enum", True)

# string fuzzy
("ACME Sdn Bhd", "ACME Sdn. Bhd.", "string", True)  # ratio ≥ 95 after stripping
("ACME Sdn Bhd", "XYZ Pte Ltd", "string", False)
```

**Test:** `cd backend && uv run pytest backend/tests/unit/test_eval_normalize.py -v`

**Acceptance:** all per-type matrix cases pass; rapidfuzz/dateparser/Babel imports work; no errant true-positives (no false equivalence between distinct values like "100" vs "1000").

**Commit message:** `feat(m12-t4): eval.normalize — type-dispatched canonicalizers (rapidfuzz + dateparser + Babel)`

---

## Task 5 — L2 LLM judge + cache + tests

**Scope:** LLM-as-judge module (off-by-default, batched, cached). Uses `get_provider_for_model` adapter — no Claude SDK recursion.

**Files:**

- `backend/app/eval/judge.py` (new)
- `backend/tests/unit/test_eval_judge.py` (new — mocks provider)

**Code sketch:**

```python
import hashlib
import json
from pathlib import Path
from typing import Any, Optional, NamedTuple

from app.config import get_settings
from app.provider import get_provider_for_model
from app.provider.base import TextBlock
from app.schemas.schema_field import SchemaField
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    eval_judge_cache_dir,
    eval_judge_cache_path,
)


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "idx": {"type": "integer"},
                    "equivalent": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["idx", "equivalent", "reason"],
            },
        },
    },
    "required": ["verdicts"],
}


def _hash_pair(field_name: str, truth: str, pred: str) -> str:
    h = hashlib.sha256()
    h.update(field_name.encode("utf-8"))
    h.update(b"\x00")
    h.update(truth.encode("utf-8"))
    h.update(b"\x00")
    h.update(pred.encode("utf-8"))
    return h.hexdigest()


class JudgeVerdict(NamedTuple):
    equivalent: bool
    reason: str
    model: str
    cached: bool


def _read_cache(workspace: Path, slug: str, sha: str) -> Optional[JudgeVerdict]:
    p = eval_judge_cache_path(workspace, slug, sha)
    if not p.exists():
        return None
    blob = json.loads(p.read_text(encoding="utf-8"))
    return JudgeVerdict(
        equivalent=blob["equivalent"],
        reason=blob.get("reason", ""),
        model=blob.get("model", ""),
        cached=True,
    )


def _write_cache(workspace: Path, slug: str, sha: str, v: JudgeVerdict) -> None:
    eval_judge_cache_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        eval_judge_cache_path(workspace, slug, sha),
        {"equivalent": v.equivalent, "reason": v.reason, "model": v.model},
    )


async def judge_batch(
    workspace: Path,
    slug: str,
    pairs: list[tuple[SchemaField, str, str]],  # (field, truth, pred)
    *,
    model_id: Optional[str] = None,
    budget: Optional[int] = None,
) -> tuple[list[Optional[JudgeVerdict]], int]:
    """Returns (verdicts_aligned_with_input, skipped_due_to_budget).
    `None` verdict in output = budget-exceeded; caller keeps L1 verdict for that pair.
    Cached pairs never count against budget.
    """
    settings = get_settings()
    model_id = model_id or settings.llm_judge_model
    budget = budget if budget is not None else settings.llm_judge_budget_per_eval

    out: list[Optional[JudgeVerdict]] = [None] * len(pairs)
    uncached_idx: list[int] = []
    shas: list[str] = []

    for i, (field, t, p) in enumerate(pairs):
        sha = _hash_pair(field.name, t, p)
        shas.append(sha)
        cached = _read_cache(workspace, slug, sha)
        if cached is not None:
            out[i] = cached
        else:
            uncached_idx.append(i)

    # Apply budget to uncached only
    budgeted_idx = uncached_idx[:budget]
    skipped = len(uncached_idx) - len(budgeted_idx)

    if not budgeted_idx:
        return out, skipped

    # Build judge prompt
    items = []
    for j, i in enumerate(budgeted_idx):
        f, t, p = pairs[i]
        items.append({
            "idx": j,
            "field": f.name,
            "description": (f.description or "")[:300],
            "truth": t,
            "pred": p,
        })

    system_prompt = (
        "You judge whether two strings refer to the same value for a given field. "
        "Output JSON {verdicts: [{idx, equivalent, reason}]}. "
        "Equivalent means the values would be considered the same by a domain expert "
        "for this field's purpose — formatting differences, abbreviations, and synonyms "
        "are equivalent; numerically or semantically distinct values are not."
    )
    user_text = "Judge each pair:\n" + json.dumps(items, ensure_ascii=False)

    provider = get_provider_for_model(model_id)
    result = await provider.extract(
        model_id=model_id,
        system_prompt=system_prompt,
        user_content=[TextBlock(type="text", text=user_text)],
        response_schema=JUDGE_SCHEMA,
        params={"temperature": 0.0},
    )

    try:
        verdicts = result.raw_json["verdicts"]
    except (KeyError, TypeError):
        # Judge HTTP succeeded but malformed → keep L1
        return out, skipped + len(budgeted_idx)

    for v in verdicts:
        try:
            j = v["idx"]
            i = budgeted_idx[j]
            jv = JudgeVerdict(
                equivalent=bool(v["equivalent"]),
                reason=str(v.get("reason", "")),
                model=model_id,
                cached=False,
            )
            out[i] = jv
            _write_cache(workspace, slug, shas[i], jv)
        except (KeyError, IndexError, TypeError):
            continue

    return out, skipped
```

**Test cases (test_eval_judge.py, mocking provider via `monkeypatch`):**

- cache hit returns cached verdict, no provider call
- cache miss → provider called once, result written to cache
- budget exceeded → remaining pairs return None in output, `skipped > 0`
- malformed provider response → all-None output, no crash
- hash collision-resistant: same (rv, pv) under field "a" vs field "b" produces distinct cache entries
- empty input → returns ([], 0)

**Test:** `cd backend && uv run pytest backend/tests/unit/test_eval_judge.py -v`

**Acceptance:** 6 cases pass; no real network calls in tests; cache directory created lazily.

**Commit message:** `feat(m12-t5): eval.judge — gemini-flash-lite-latest LLM-as-judge with content-addressed cache`

---

## Task 6 — eval/score.py orchestrator + pivot + tests

**Scope:** the core that ties presence + normalize + judge together into per-cell verdicts. Writes the directory artifact.

**Files:**

- `backend/app/eval/score.py` (moved + heavily restructured from `tools/score.py`)
- `backend/app/eval/pivot.py` (new — cells → CSV)
- `backend/tests/unit/test_eval_score.py` (replaces test_score.py)
- `backend/tests/unit/test_eval_pivot.py` (new)

**Code sketch (score.py):**

```python
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.eval.judge import JudgeVerdict, judge_batch
from app.eval.normalize import normalize_equivalent
from app.eval.pivot import cells_to_csv
from app.eval.presence import (
    DEFAULT_PROJECT_POLICY,
    AbsentPolicy,
    is_absent,
    resolve_policy,
)
from app.eval.types import CellStatus, CellVerdict, VerdictSource
from app.schemas.schema_field import SchemaField
from app.schemas.score import FieldScore, ScoreResultSummary
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    eval_cells_path,
    eval_dir,
    eval_matrix_path,
    eval_meta_path,
    eval_summary_path,
    metrics_dir,
    predictions_draft_dir,
    project_json_path,
    reviewed_dir,
)


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _str_or_none(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


async def score(
    workspace: Path,
    project_id: str,
    schema: list[SchemaField],
    predictions: dict[str, list[dict[str, Any]]],
    reviewed: dict[str, list[dict[str, Any]]],
    *,
    use_llm_judge: bool = False,
    project_policy: AbsentPolicy = DEFAULT_PROJECT_POLICY,
) -> tuple[ScoreResultSummary, list[CellVerdict]]:
    """Orchestrate L1 + (L2) + L3 over reviewed × schema.
    Returns (summary, all_cells)."""

    cells: list[CellVerdict] = []
    errors: list[str] = []
    judge_used = 0
    judge_skipped_budget = 0

    # First pass: build all cells with L1 + L3 verdicts; collect L2 candidates
    l2_candidates: list[tuple[int, SchemaField, str, str]] = []  # (cell_idx, field, truth_str, pred_str)

    for filename, reviewed_entities in reviewed.items():
        if filename not in predictions:
            errors.append(f"doc {filename} has reviewed but no prediction")
            for entity_idx, r_ent in enumerate(reviewed_entities):
                for field in schema:
                    rv = r_ent.get(field.name)
                    policy = resolve_policy(field, project_policy)
                    if is_absent(rv, policy):
                        cells.append(_cell_absent_both(filename, entity_idx, field.name))
                    else:
                        cells.append(_cell_missing(filename, entity_idx, field, rv))
            continue

        prediction_entities = predictions[filename]
        if len(prediction_entities) != len(reviewed_entities):
            errors.append(
                f"doc {filename}: predicted {len(prediction_entities)} entities, "
                f"reviewed {len(reviewed_entities)} — grading the overlap only"
            )

        for entity_idx, r_ent in enumerate(reviewed_entities):
            p_ent = prediction_entities[entity_idx] if entity_idx < len(prediction_entities) else None

            for field in schema:
                policy = resolve_policy(field, project_policy)
                rv = r_ent.get(field.name) if r_ent else None
                pv = p_ent.get(field.name) if p_ent else None
                r_absent = is_absent(rv, policy)
                p_absent = is_absent(pv, policy) if p_ent is not None else True

                if r_absent and p_absent:
                    cells.append(_cell_absent_both(filename, entity_idx, field.name))
                    continue

                if r_absent and not p_absent:
                    cells.append(_cell_spurious(filename, entity_idx, field, pv))
                    continue

                if not r_absent and p_absent:
                    cells.append(_cell_missing(filename, entity_idx, field, rv))
                    continue

                # Both present — try exact, then normalize
                rv_s, pv_s = str(rv), str(pv)
                if rv_s == pv_s:
                    cells.append(CellVerdict(
                        filename=filename, entity_idx=entity_idx, field=field.name,
                        status="correct", truth=rv_s, pred=pv_s,
                        verdict_source="exact",
                    ))
                    continue

                norm = normalize_equivalent(rv, pv, field)
                if norm.equivalent:
                    cells.append(CellVerdict(
                        filename=filename, entity_idx=entity_idx, field=field.name,
                        status="correct", truth=rv_s, pred=pv_s,
                        verdict_source="normalize", normalizer=norm.normalizer,
                    ))
                    continue

                # L1 says wrong; mark provisional, queue for optional L2
                provisional = CellVerdict(
                    filename=filename, entity_idx=entity_idx, field=field.name,
                    status="wrong", truth=rv_s, pred=pv_s,
                    verdict_source="normalize", normalizer=norm.normalizer,
                )
                cells.append(provisional)
                if use_llm_judge:
                    l2_candidates.append((len(cells) - 1, field, rv_s, pv_s))

    # L2 pass — only on wrong-after-L1 pairs
    if use_llm_judge and l2_candidates:
        verdicts, skipped = await judge_batch(
            workspace, project_id,
            [(f, t, p) for (_, f, t, p) in l2_candidates],
        )
        judge_skipped_budget = skipped
        for (cell_idx, _f, _t, _p), v in zip(l2_candidates, verdicts, strict=True):
            if v is None:
                continue
            judge_used += 1
            if v.equivalent:
                # upgrade to correct
                cells[cell_idx] = cells[cell_idx].model_copy(update={
                    "status": "correct",
                    "verdict_source": "llm_judge",
                    "judge_reason": v.reason,
                    "judge_model": v.model,
                })
            else:
                cells[cell_idx] = cells[cell_idx].model_copy(update={
                    "verdict_source": "llm_judge",
                    "judge_reason": v.reason,
                    "judge_model": v.model,
                })

    # Aggregate
    per_field, macro_f1, doc_acc, n_reviewed = _aggregate(cells, schema, reviewed)

    summary = ScoreResultSummary(
        n_docs=len(reviewed) + sum(1 for fn in predictions if fn not in reviewed),
        n_reviewed=n_reviewed,
        macro_f1=macro_f1,
        doc_accuracy=doc_acc,
        per_field=per_field,
        errors=errors,
        ts=_now_ts(),
        schema_field_count=len(schema),
        judge_used=judge_used,
        judge_skipped_budget=judge_skipped_budget,
    )
    return summary, cells


def _cell_absent_both(filename, entity_idx, field_name):
    return CellVerdict(filename=filename, entity_idx=entity_idx, field=field_name,
                       status="absent_both", verdict_source="presence")

def _cell_missing(filename, entity_idx, field, truth_v):
    return CellVerdict(filename=filename, entity_idx=entity_idx, field=field.name,
                       status="missing", truth=_str_or_none(truth_v),
                       verdict_source="presence")

def _cell_spurious(filename, entity_idx, field, pred_v):
    return CellVerdict(filename=filename, entity_idx=entity_idx, field=field.name,
                       status="spurious", pred=_str_or_none(pred_v),
                       verdict_source="presence")


def _aggregate(cells, schema, reviewed):
    # per-field tp/fp/fn/support + accuracy
    counts = {f.name: {"tp": 0, "fp": 0, "fn": 0, "support": 0,
                       "correct": 0, "total": 0} for f in schema}
    for c in cells:
        if c.field not in counts: continue
        d = counts[c.field]
        d["total"] += 1
        if c.status == "correct": d["correct"] += 1; d["tp"] += 1; d["support"] += 1
        elif c.status == "wrong": d["fp"] += 1; d["fn"] += 1; d["support"] += 1
        elif c.status == "missing": d["fn"] += 1; d["support"] += 1
        elif c.status == "spurious": d["fp"] += 1

    per_field = []
    for f in schema:
        d = counts[f.name]
        precision = (d["tp"] / (d["tp"] + d["fp"])) if (d["tp"] + d["fp"]) > 0 else 0.0
        recall = (d["tp"] / (d["tp"] + d["fn"])) if (d["tp"] + d["fn"]) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        accuracy = (d["correct"] / d["total"]) if d["total"] > 0 else 0.0
        per_field.append(FieldScore(
            field=f.name, tp=d["tp"], fp=d["fp"], fn=d["fn"], support=d["support"],
            precision=precision, recall=recall, f1=f1, accuracy=accuracy,
        ))

    macro_f1 = sum(p.f1 for p in per_field) / len(per_field) if per_field else 0.0

    # doc_accuracy: docs where every non-absent_both cell is correct AND entity counts match
    docs_seen = {}
    for c in cells:
        docs_seen.setdefault(c.filename, []).append(c)
    n_reviewed_graded = sum(1 for fn in reviewed if fn in docs_seen)
    doc_correct = 0
    for fn, c_list in docs_seen.items():
        if fn not in reviewed: continue
        ok = all(c.status in ("correct", "absent_both") for c in c_list)
        if ok: doc_correct += 1
    doc_acc = (doc_correct / n_reviewed_graded) if n_reviewed_graded > 0 else 0.0

    return per_field, macro_f1, doc_acc, n_reviewed_graded


async def run_eval(
    workspace: Path,
    project_id: str,
    *,
    use_llm_judge: bool = False,
    experiment_id: Optional[str] = None,  # for run_experiment_eval path
) -> ScoreResultSummary:
    from app.tools.schema import read_schema
    schema = await read_schema(workspace, project_id)

    # Pick predictions source
    if experiment_id:
        from app.workspace.paths import experiment_predictions_dir
        pd_path = experiment_predictions_dir(workspace, project_id, experiment_id)
    else:
        pd_path = predictions_draft_dir(workspace, project_id)

    predictions, reviewed = await _load_pred_and_reviewed(workspace, project_id, pd_path)
    summary, cells = await score(
        workspace, project_id, schema, predictions, reviewed,
        use_llm_judge=use_llm_judge,
    )

    # Persist directory artifact
    async with project_lock(workspace, project_id):
        d = eval_dir(workspace, project_id, summary.ts)
        d.mkdir(parents=True, exist_ok=True)
        atomic_write_json(eval_summary_path(workspace, project_id, summary.ts),
                          summary.model_dump(mode="json"))
        _write_cells_jsonl(eval_cells_path(workspace, project_id, summary.ts), cells)
        _write_matrix_csv(eval_matrix_path(workspace, project_id, summary.ts),
                          schema, cells)
        _write_meta(eval_meta_path(workspace, project_id, summary.ts),
                    workspace, project_id, summary, experiment_id)
    return summary


async def _load_pred_and_reviewed(workspace, project_id, pd_path):
    predictions, reviewed = {}, {}
    if pd_path.exists():
        for p in sorted(pd_path.glob("*.json")):
            blob = json.loads(p.read_text())
            predictions[p.stem] = blob.get("entities", [])
    rd = reviewed_dir(workspace, project_id)
    if rd.exists():
        for p in sorted(rd.glob("*.json")):
            blob = json.loads(p.read_text())
            reviewed[p.stem] = blob.get("entities", [])
    return predictions, reviewed


def _write_cells_jsonl(path: Path, cells: list[CellVerdict]) -> None:
    lines = "\n".join(json.dumps(c.model_dump(mode="json"), ensure_ascii=False) for c in cells)
    path.write_text(lines + ("\n" if lines else ""), encoding="utf-8")


def _write_matrix_csv(path: Path, schema, cells: list[CellVerdict]) -> None:
    from app.eval.pivot import cells_to_csv
    path.write_text(cells_to_csv(schema, cells), encoding="utf-8")


def _write_meta(path: Path, workspace, project_id, summary, experiment_id):
    blob = json.loads(project_json_path(workspace, project_id).read_text())
    meta = {
        "prompt_id": blob.get("active_prompt_id"),
        "model_id": blob.get("active_model_id"),
        "experiment_id": experiment_id,
        "judge_used": summary.judge_used,
        "judge_skipped_budget": summary.judge_skipped_budget,
        "ts": summary.ts,
        "schema_field_count": summary.schema_field_count,
        "n_reviewed": summary.n_reviewed,
    }
    atomic_write_json(path, meta)
```

**Code sketch (pivot.py):**

```python
import csv
import io
from app.eval.types import CellVerdict
from app.schemas.schema_field import SchemaField

SEP = "·"

def cells_to_csv(schema: list[SchemaField], cells: list[CellVerdict]) -> str:
    """Pivot per-cell verdicts into wide-format CSV.
    One row per (filename, entity_idx); two columns per schema field
    (truth, pred); n_fields_correct precomputed."""
    # Group cells by (filename, entity_idx)
    rows: dict[tuple[str, int], dict[str, CellVerdict]] = {}
    for c in cells:
        rows.setdefault((c.filename, c.entity_idx), {})[c.field] = c

    headers = ["filename", "entity_idx", "n_fields_correct"]
    for f in schema:
        headers.append(f"{f.name}{SEP}truth")
        headers.append(f"{f.name}{SEP}pred")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for (filename, entity_idx) in sorted(rows.keys()):
        cell_map = rows[(filename, entity_idx)]
        n_correct = sum(1 for c in cell_map.values() if c.status == "correct")
        row = [filename, entity_idx, n_correct]
        for f in schema:
            c = cell_map.get(f.name)
            row.append(c.truth or "" if c else "")
            row.append(c.pred or "" if c else "")
        writer.writerow(row)
    return buf.getvalue()
```

**Test cases (test_eval_score.py):** ports test_score.py cases + adds:

- multi-entity mismatched lengths → doc_accuracy < 1.0, extra reviewed entities → missing cells
- absent_policy=lenient: `{"a":1, "b":null}` vs `{"a":1}` → absent_both for `b`
- absent_policy=strict: same → spurious for `b` (null is "present")
- exact "100" == "100" → correct verdict_source=exact
- "123.10" vs "123.1" with type=number → correct verdict_source=normalize, normalizer=number
- use_llm_judge=True with monkey-patched judge returning equivalent=True → cell upgraded to correct, verdict_source=llm_judge
- budget exhausted → judge_skipped_budget > 0, cells retain L1 verdict

**Test cases (test_eval_pivot.py):**

- 1 doc, 3 fields, all correct → 1 row, n_fields_correct=3
- 2 entities → 2 rows
- absent values → empty cells in CSV
- field name with `_` (e.g. `tax_id`) → `tax_id·truth` header, no escaping issues

**Test:** `cd backend && uv run pytest backend/tests/unit/test_eval_score.py backend/tests/unit/test_eval_pivot.py -v`

**Acceptance:** all cases pass; `metrics/eval_<ts>/` directory created with 4 files; no regressions in `test_eval_normalize.py` and `test_eval_presence.py`.

**Commit message:** `feat(m12-t6): eval.score orchestrator + pivot — per-cell verdicts + matrix.csv`

---

## Task 7 — tools/score.py thin re-export + tool registration param

**Scope:** keep the `score` tool name binding stable for MCP registration; add `use_llm_judge` arg.

**Files:**

- `backend/app/tools/score.py` (slim down to re-export)
- `backend/app/tools/__init__.py` (add `use_llm_judge` to `score` tool schema; same for `run_experiment_eval`)

**Code sketch (tools/score.py):**

```python
# Thin re-export — actual implementation lives in app.eval.score.
from app.eval.score import score, run_eval

__all__ = ["score", "run_eval"]
```

**Code sketch (tools/__init__.py changes):**

- `score` tool: add `use_llm_judge: {"type": "boolean", "default": False}` to schema. In handler, pass through to `run_eval(..., use_llm_judge=args.get("use_llm_judge", False))`.
- `run_experiment_eval` tool: same.

**Test:** `cd backend && uv run pytest backend/tests/unit/test_tool_registration.py -v`

**Acceptance:** existing tool registration test still passes; MCP server starts; `score` tool callable with and without `use_llm_judge`.

**Commit message:** `feat(m12-t7): tools/score thin re-export + use_llm_judge param on score & run_experiment_eval`

---

## Task 8 — HTTP routes: /eval, /score accept use_llm_judge; new GETs for cells/matrix/summary; lazy legacy read

**Scope:** wire the directory artifact through HTTP; preserve legacy file form on read.

**Files:**

- `backend/app/api/routes/eval.py`
- `backend/app/api/routes/experiments.py` (run_experiment_eval param)
- `backend/app/api/routes/_safety.py` (if needed for ts validation)

**Code sketch (eval.py additions):**

```python
from pydantic import BaseModel

class _EvalBody(BaseModel):
    use_llm_judge: bool = False


@router.post("/lab/projects/{slug}/eval")
async def post_eval(slug: str, body: Optional[_EvalBody] = None) -> dict:
    # ... existing checks ...
    result = await run_eval(
        ws, slug,
        use_llm_judge=body.use_llm_judge if body else False,
    )
    return result.model_dump(mode="json")


# Mirror for /score (M11 symmetric envelope)
@router.post("/lab/projects/{slug}/score")
async def post_score(slug: str, body: Optional[_EvalBody] = None) -> dict:
    # ... same as eval but with structured error envelope ...
    ...


@router.get("/lab/projects/{slug}/evals")
async def list_evals(slug: str) -> list[dict]:
    """List all eval ts'es with meta + summary header."""
    md = metrics_dir(settings.workspace_root, slug)
    out = []
    if not md.exists(): return []
    for child in sorted(md.iterdir(), reverse=True):
        if child.is_dir() and child.name.startswith("eval_"):
            ts = child.name[len("eval_"):]
            try:
                meta = json.loads((child / "meta.json").read_text())
                summary = json.loads((child / "summary.json").read_text())
                out.append({"ts": ts, "meta": meta,
                            "doc_accuracy": summary.get("doc_accuracy"),
                            "macro_f1": summary.get("macro_f1"),
                            "n_reviewed": summary.get("n_reviewed")})
            except (FileNotFoundError, json.JSONDecodeError):
                continue
        elif child.is_file() and child.name.startswith("eval_") and child.suffix == ".json":
            # Legacy form
            ts = child.stem[len("eval_"):]
            try:
                blob = json.loads(child.read_text())
                out.append({"ts": ts, "meta": {"legacy": True},
                            "doc_accuracy": None,
                            "macro_f1": blob.get("macro_f1"),
                            "n_reviewed": blob.get("n_reviewed")})
            except json.JSONDecodeError:
                continue
    return out


@router.get("/lab/projects/{slug}/eval/latest")
async def get_eval_latest_dir(slug: str) -> dict:
    """Return summary.json of the most-recent eval (new dir-form preferred,
    legacy file accepted)."""
    md = metrics_dir(settings.workspace_root, slug)
    if not md.exists():
        raise HTTPException(status_code=404, detail={"error_code": "eval_not_found"})
    # Prefer dir form
    dirs = sorted([p for p in md.iterdir() if p.is_dir() and p.name.startswith("eval_")])
    if dirs:
        summary_p = dirs[-1] / "summary.json"
        if summary_p.exists():
            return json.loads(summary_p.read_text())
    files = sorted(md.glob("eval_*.json"))
    if files:
        return json.loads(files[-1].read_text())
    raise HTTPException(status_code=404, detail={"error_code": "eval_not_found"})


@router.get("/lab/projects/{slug}/eval/{ts}/summary.json")
async def get_eval_summary(slug: str, ts: str) -> dict:
    safe_slug(slug)
    _validate_ts(ts)
    p = eval_summary_path(settings.workspace_root, slug, ts)
    if not p.exists():
        # Legacy fallback
        legacy = metrics_path(settings.workspace_root, slug, f"eval_{ts}")
        if legacy.exists():
            return json.loads(legacy.read_text())
        raise HTTPException(status_code=404, detail={"error_code": "eval_not_found"})
    return json.loads(p.read_text())


@router.get("/lab/projects/{slug}/eval/{ts}/cells.jsonl")
async def get_eval_cells(slug: str, ts: str):
    from fastapi.responses import PlainTextResponse
    safe_slug(slug)
    _validate_ts(ts)
    p = eval_cells_path(settings.workspace_root, slug, ts)
    if not p.exists():
        raise HTTPException(status_code=404, detail={"error_code": "eval_cells_not_found"})
    return PlainTextResponse(p.read_text(), media_type="application/x-ndjson")


@router.get("/lab/projects/{slug}/eval/{ts}/matrix.csv")
async def get_eval_matrix(slug: str, ts: str):
    from fastapi.responses import PlainTextResponse
    safe_slug(slug)
    _validate_ts(ts)
    p = eval_matrix_path(settings.workspace_root, slug, ts)
    if not p.exists():
        raise HTTPException(status_code=404, detail={"error_code": "eval_matrix_not_found"})
    return PlainTextResponse(p.read_text(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="eval_{ts}.csv"'})


_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$|^latest$")
def _validate_ts(ts: str):
    if not _TS_RE.match(ts):
        raise HTTPException(status_code=400, detail={"error_code": "invalid_ts"})
```

**Test:** `cd backend && uv run pytest backend/tests/unit/test_routes_eval.py -v` (new test file).

**Test cases:**

- POST /eval with `{"use_llm_judge":false}` → creates dir, returns summary
- GET /evals → lists current evals
- GET /eval/<ts>/summary.json → returns summary
- GET /eval/<ts>/cells.jsonl → returns jsonl text
- GET /eval/<ts>/matrix.csv → returns csv with `attachment` header
- GET /eval/latest → returns latest summary (dir form)
- GET /eval/latest with legacy eval_*.json present and no dirs → returns legacy summary
- Invalid ts (`../etc`) → 400 invalid_ts

**Acceptance:** all 8 cases pass; symmetry test still green; legacy snapshot reads work.

**Commit message:** `feat(m12-t8): http routes for dir-form eval (cells/matrix/summary) + lazy legacy read`

---

## Task 9 — Symmetry invariant + autoresearch tolerance

**Scope:** register new tools/routes in symmetry invariant; ensure autoresearch's score reads still work.

**Files:**

- `backend/tests/unit/test_symmetry_invariant.py`
- `backend/app/jobs/autoresearch.py` (only if it reads `metrics/*.json` directly — check + adapt)

**Code sketch (test addition):**

The symmetry test enumerates registered tools and asserts each has a route. Add expected mapping for tools where applicable. For new HTTP-only routes (`GET /evals`, `GET /eval/<ts>/cells.jsonl`, etc.), add them to a `_HTTP_ONLY` whitelist with one-line justification: "static artifact serve, no agent-bound tool counterpart needed."

**Autoresearch check:**

```bash
grep -n "metrics" backend/app/jobs/autoresearch.py
```

If it reads `metrics_path(...)` directly (file form), wrap with the same `is_file/is_dir` lazy logic. If it only calls `run_eval()`, no change.

**Test:** `cd backend && uv run pytest backend/tests/unit/test_symmetry_invariant.py backend/tests/unit/test_autoresearch.py -v`

**Acceptance:** symmetry test green; autoresearch tests green.

**Commit message:** `test(m12-t9): symmetry invariant for new eval routes + autoresearch tolerates dir-form`

---

## Task 10 — Backend integration smoke

**Scope:** run a real `/eval` end-to-end on a fixture project with mixed normalize-equivalent + truly-wrong cells. No real LLM judge.

**Files:**

- `backend/tests/integration/test_eval_e2e.py` (new)

**Code sketch:**

```python
async def test_eval_e2e(tmp_workspace, sample_project):
    # Pre-seed: project with 3 schema fields (string/number/date),
    # 4 reviewed docs, 4 predictions_draft with mixed states:
    # - doc1: all 3 fields exact match
    # - doc2: number field "123.10" vs "123.1" (normalize)
    # - doc3: date "2024/3/12" vs "2024-03-12" (normalize)
    # - doc4: amount field "1000" vs "1500" (truly wrong)

    result = await run_eval(workspace, slug, use_llm_judge=False)

    assert result.n_reviewed == 4
    assert result.doc_accuracy == 0.75  # 3/4 docs fully correct
    assert (eval_dir(workspace, slug, result.ts)).exists()
    assert (eval_cells_path(workspace, slug, result.ts)).exists()
    assert (eval_matrix_path(workspace, slug, result.ts)).exists()

    # cells.jsonl content
    lines = (eval_cells_path(...)).read_text().splitlines()
    cells = [json.loads(l) for l in lines]
    assert len(cells) == 4 * 3  # 4 docs × 3 fields
    normalize_count = sum(1 for c in cells if c["verdict_source"] == "normalize")
    assert normalize_count == 2  # doc2 number + doc3 date

    # matrix.csv
    csv_text = (eval_matrix_path(...)).read_text()
    assert "filename" in csv_text.splitlines()[0]
    assert "·truth" in csv_text.splitlines()[0]
    assert "·pred" in csv_text.splitlines()[0]
```

**Test:** `cd backend && uv run pytest backend/tests/integration/test_eval_e2e.py -v`

**Acceptance:** e2e passes; on-disk artifacts match expectations.

**Commit message:** `test(m12-t10): backend e2e for dir-form eval with mixed L1 normalize cases`

---

## Task 11 — Frontend types + eval store + api helpers

**Scope:** frontend data layer for matrix page.

**Files:**

- `frontend/src/types/eval.ts` (new)
- `frontend/src/stores/eval.ts` (new)
- `frontend/src/lib/api.ts` (additions)

**Code sketch (types/eval.ts):**

```typescript
export interface FieldScoreSummary {
  field: string
  tp: number; fp: number; fn: number; support: number
  precision: number; recall: number; f1: number
  accuracy: number | null
}

export interface ScoreResultSummary {
  n_docs: number
  n_reviewed: number
  macro_f1: number
  doc_accuracy: number | null
  per_field: FieldScoreSummary[]
  errors: string[]
  ts: string
  schema_field_count: number
  judge_used: number
  judge_skipped_budget: number
}

export type CellStatus = "correct" | "wrong" | "missing" | "spurious" | "absent_both"

export interface CellVerdict {
  filename: string
  entity_idx: number
  field: string
  status: CellStatus
  truth: string | null
  pred: string | null
  verdict_source: "exact" | "normalize" | "llm_judge" | "presence"
  normalizer: string | null
  judge_reason: string | null
  judge_model: string | null
}

export interface EvalListEntry {
  ts: string
  meta: { prompt_id?: string; model_id?: string; experiment_id?: string | null; legacy?: boolean }
  doc_accuracy: number | null
  macro_f1: number
  n_reviewed: number
}
```

**Code sketch (stores/eval.ts):**

```typescript
import { create } from 'zustand'
import type { ScoreResultSummary, CellVerdict, EvalListEntry } from '../types/eval'

interface State {
  list: Record<string, EvalListEntry[]>            // by project slug
  summary: Record<string, ScoreResultSummary>      // by `${slug}|${ts}`
  cells: Record<string, CellVerdict[]>             // by `${slug}|${ts}`
  loadList: (slug: string) => Promise<void>
  loadSummary: (slug: string, ts: string) => Promise<void>
  loadCells: (slug: string, ts: string) => Promise<void>
  invalidate: (slug: string) => void
}

export const useEval = create<State>((set, get) => ({
  list: {}, summary: {}, cells: {},

  invalidate(slug) { /* drop slug-keyed entries */ },

  async loadList(slug) {
    const r = await fetch(`/lab/projects/${encodeURIComponent(slug)}/evals`)
    const list = r.ok ? await r.json() as EvalListEntry[] : []
    set(s => ({ list: { ...s.list, [slug]: list } }))
  },

  async loadSummary(slug, ts) {
    const key = `${slug}|${ts}`
    if (get().summary[key]) return
    const r = await fetch(`/lab/projects/${encodeURIComponent(slug)}/eval/${ts}/summary.json`)
    if (!r.ok) return
    set(s => ({ summary: { ...s.summary, [key]: await r.json() } }))
  },

  async loadCells(slug, ts) {
    const key = `${slug}|${ts}`
    if (get().cells[key]) return
    const r = await fetch(`/lab/projects/${encodeURIComponent(slug)}/eval/${ts}/cells.jsonl`)
    if (!r.ok) return
    const text = await r.text()
    const cells = text.split('\n').filter(Boolean).map(l => JSON.parse(l) as CellVerdict)
    set(s => ({ cells: { ...s.cells, [key]: cells } }))
  },
}))
```

**Test:** `cd frontend && npx tsc --noEmit && npm test -- eval`

**Acceptance:** type compile passes; store unit-test covers list/summary/cells loading and caching.

**Commit message:** `feat(m12-t11): frontend eval types + store + api helpers`

---

## Task 12 — Frontend route + EvalMatrixPage

**Scope:** new `/projects/:slug/eval/:ts` route renders matrix grid with filters and cell drilldown.

**Files:**

- `frontend/src/components/EvalMatrix/EvalMatrixPage.tsx` (new)
- `frontend/src/components/EvalMatrix/MatrixGrid.tsx` (new)
- `frontend/src/components/EvalMatrix/CellDrilldown.tsx` (new)
- `frontend/src/components/EvalMatrix/filters.ts` (new)
- `frontend/src/App.tsx` (route registration)

**Code sketch (EvalMatrixPage.tsx):**

```tsx
export default function EvalMatrixPage() {
  const { slug, ts } = useParams()
  const { loadSummary, loadCells, summary, cells } = useEval(...)

  useEffect(() => {
    if (slug && ts) {
      loadSummary(slug, ts)
      loadCells(slug, ts)
    }
  }, [slug, ts])

  const summaryKey = `${slug}|${ts}`
  const sum = summary[summaryKey]
  const cs = cells[summaryKey]
  const [filter, setFilter] = useState<'all' | 'errors_only'>('errors_only')
  const [drilldown, setDrilldown] = useState<CellVerdict | null>(null)

  if (!sum) return <div>Loading…</div>

  return (
    <div className="eval-matrix-page">
      <header>
        <h2>eval · {ts}</h2>
        <div className="stats">
          <span>文档准确率 {pct(sum.doc_accuracy)}</span>
          <span className="muted">macro F1 {sum.macro_f1.toFixed(2)}</span>
          <span className="muted">{sum.n_reviewed} docs</span>
          {sum.judge_used > 0 && <span>LLM judged: {sum.judge_used}</span>}
        </div>
        <div className="toolbar">
          <label><input type="checkbox" checked={filter==='errors_only'}
                       onChange={e => setFilter(e.target.checked?'errors_only':'all')} />
                 只看错误</label>
          <a href={`/lab/projects/${slug}/eval/${ts}/matrix.csv`} download>
            下载 CSV
          </a>
        </div>
      </header>
      {cs && (
        <MatrixGrid
          cells={cs}
          schema={schema}  // pulled from another store
          filter={filter}
          onCellClick={c => setDrilldown(c)}
        />
      )}
      {drilldown && (
        <CellDrilldown
          cell={drilldown}
          onClose={() => setDrilldown(null)}
          onOpenReview={() => navigate(`/projects/${slug}/review/${drilldown.filename}?field=${drilldown.field}`)}
        />
      )}
    </div>
  )
}
```

**Code sketch (MatrixGrid.tsx):**

- Pivots cells into rows keyed by `(filename, entity_idx)`
- Each row: sticky filename col, then for each field: a single cell showing `truth` over `pred` (two lines), background tinted by status (correct=green-3, wrong=rose-3, missing=ochre-3, spurious=ochre-1, absent_both=transparent)
- Click cell → opens drilldown
- "只看错误" hides rows where every cell is correct or absent_both
- Uses design tokens per [[project_design_token_roles]]; no hex colors

**Code sketch (CellDrilldown.tsx):**

- Right side panel
- Header: filename · field · entity_idx
- "正确值"行: shows truth
- "当前值"行: shows pred
- "判定依据"行: shows verdict_source + normalizer name (if any) or judge_reason (if llm_judge)
- "查看 doc" button → navigate to review mode with field focused

**App.tsx:**

```tsx
<Route path="/projects/:slug/eval/:ts" element={<EvalMatrixPage />} />
<Route path="/projects/:slug/eval/latest" element={<EvalMatrixPage latest />} />
```

**Test:** `cd frontend && npx tsc --noEmit && npm test -- EvalMatrix`

**Acceptance:** tsc clean; smoke test renders 4-row × 3-col matrix from fixtures; "只看错误" filters correctly; cell click opens drilldown.

**Commit message:** `feat(m12-t12): frontend EvalMatrixPage + MatrixGrid + CellDrilldown`

---

## Task 13 — Compare page

**Scope:** `/projects/:slug/eval/compare?a=<ts1>&b=<ts2>` side-by-side matrix with delta highlighting.

**Files:**

- `frontend/src/components/EvalMatrix/EvalCompare.tsx` (new)
- `frontend/src/App.tsx` (route)

**Code sketch:**

```tsx
export default function EvalCompare() {
  const { slug } = useParams()
  const [params] = useSearchParams()
  const a = params.get('a'), b = params.get('b')
  // Load both summaries + cells
  // Render two MatrixGrids side by side OR a "diff" matrix:
  //   for each (filename, field), show: status_a / status_b
  //   color: green if both correct, red if both wrong, ochre if regression, moss if improvement
  // Top: delta summary table (doc_accuracy a→b, macro_f1 a→b, per_field deltas sorted by |Δ|)
}
```

**Test:** `cd frontend && npm test -- EvalCompare`

**Acceptance:** tsc clean; smoke renders both columns, delta header.

**Commit message:** `feat(m12-t13): frontend eval compare page (a vs b)`

---

## Task 14 — Chat EvalCard updates + Spine metrics/ leaf click

**Scope:** make the chat-side eval card link to the new matrix page; spine clickable.

**Files:**

- `frontend/src/components/Chat/EvalCard.tsx`
- `frontend/src/components/Spine/FSSpine.tsx`

**Code sketch (EvalCard.tsx):**

- Header: prefix with doc_accuracy (if present) before macro_f1
- Footer: `<a href={`/projects/${slug}/eval/${ts}`}>↗ open full matrix</a>` when ts is known

**Code sketch (FSSpine.tsx):**

- `metrics/` group: each leaf (an eval_ts) becomes clickable
- onClick → router push to `/projects/:slug/eval/:ts`

**Test:** `cd frontend && npx tsc --noEmit && npm test -- EvalCard`

**Acceptance:** tsc clean; existing EvalCard tests pass (or updated); spine leaf click triggers router push.

**Commit message:** `feat(m12-t14): EvalCard footer link + spine metrics/ leaf clickable`

---

## Task 15 — `/compare` skill route in emerge_extractor.md

**Scope:** documented agent flow for `/compare <model_id>` and NL equivalents.

**Files:**

- `backend/app/skills/emerge_extractor.md`

**Code sketch (insertion after the existing slash commands section):**

Add the `/compare` section as drafted in the chat history above (in the response prior to this plan), with these specific commitments:

- Always pre-check `Bash ls reviewed/*.json | wc -l` — refuse if 0.
- Always write `models/m_<short>.json` if candidate not in project (no asking, no add_model_from_catalog).
- Always `create_experiment` (idempotent).
- Always run `score(slug)` and `run_experiment_eval(experiment_id)` once each.
- Always render markdown delta table; end with link `/projects/<slug>/eval/compare?a=<ts_baseline>&b=<ts_candidate>`.
- Never auto-`switch_active_model`; only suggest the command.
- If `doc_accuracy < 0.5` for either side, prepend a "low ground-truth coverage" warning.

**Test:** N/A (markdown). Manual spot check: skill md renders in `chat/service.py` system prompt assembly.

**Acceptance:** `cd backend && uv run pytest backend/tests/unit/test_chat_service.py -v` (no regressions; skill md still loaded).

**Commit message:** `docs(m12-t15): /compare skill route in emerge-extractor.md`

---

## Task 16 — Full backend suite + lint

**Scope:** safety net before frontend smoke.

**Files:** none new.

**Test:**
```
cd backend && uv run pytest -v
cd backend && uv run ruff check app/
```

**Acceptance:** ≤2 unrelated pre-existing failures (document them in commit message if so).

**Commit message:** `chore(m12-t16): full backend suite green after eval-as-module landed`

---

## Task 17 — Frontend lint + typecheck + tests

**Scope:** frontend safety net.

**Files:** none new.

**Test:**
```
cd frontend && npx tsc --noEmit
cd frontend && npm test
cd frontend && npm run lint
```

**Acceptance:** tsc clean; tests green; lint clean.

**Commit message:** `chore(m12-t17): frontend tsc + tests + lint green`

---

## Task 18 — Live smoke + closeout

**Scope:** end-to-end smoke on a real project; update ROADMAP.

**Steps:**

1. Pick `默沙东_小票` (has reviewed docs).
2. From chat: `/eval` → confirm new dir created.
3. Open `/projects/默沙东_小票/eval/latest` → confirm matrix renders.
4. Click a red cell → confirm drilldown shows truth/pred + opens review when clicked.
5. From chat: `/compare gemini-pro-latest` → confirm full flow: new model created, experiment run, eval done, agent renders markdown delta + link.
6. Open the compare link → confirm side-by-side matrix.
7. Download CSV → confirm content correct in Excel.
8. With `use_llm_judge=True` (via chat tool call), run on a doc with known normalize-edge cases → confirm `judge_used` > 0 and cache populated in `.eval_judge_cache/`.

**ROADMAP update:**

Add row:
```
| **M12** — eval as module (per-cell matrix + L1/L2/L3 + matrix UI + /compare skill) | `2026-05-21-m12-eval-as-module.md` | ✅ shipped + dogfooded | <commits> |
```

**Commit message:** `chore(m12-t18): closeout — live smoke + ROADMAP updated`

---

## Critical files to modify (recap)

```
backend/
├── pyproject.toml                                 (T1: +3 deps)
├── app/
│   ├── config.py                                  (T1: +2 settings)
│   ├── workspace/paths.py                         (T1: +7 helpers)
│   ├── eval/                                      (T1-T6: 6 new files)
│   ├── schemas/
│   │   ├── score.py                               (T2: +accuracy +doc_accuracy +alias)
│   │   └── schema_field.py                        (T2: +absent_policy)
│   ├── tools/
│   │   ├── score.py                               (T7: thin re-export)
│   │   └── __init__.py                            (T7: +use_llm_judge param)
│   ├── api/routes/
│   │   ├── eval.py                                (T8: +6 routes / param)
│   │   └── experiments.py                         (T8: +use_llm_judge param)
│   ├── skills/emerge_extractor.md                 (T15: /compare route)
│   └── jobs/autoresearch.py                       (T9: lazy legacy read if needed)
└── tests/
    ├── unit/test_eval_*.py                        (T3-T6: 5 new test files)
    ├── unit/test_routes_eval.py                   (T8: new)
    ├── unit/test_symmetry_invariant.py            (T9: +entries)
    └── integration/test_eval_e2e.py               (T10: new)

frontend/
├── src/
│   ├── App.tsx                                    (T12-T13: +routes)
│   ├── types/eval.ts                              (T11: new)
│   ├── stores/eval.ts                             (T11: new)
│   ├── lib/api.ts                                 (T11: +helpers)
│   ├── components/
│   │   ├── EvalMatrix/                            (T12-T13: 5 new files)
│   │   ├── Chat/EvalCard.tsx                      (T14: +link)
│   │   └── Spine/FSSpine.tsx                      (T14: metrics/ leaf click)
```

## Acceptance criteria (the milestone is done when)

1. ☐ `pytest backend/tests/ -v` green (≤2 pre-existing unrelated failures documented)
2. ☐ `npx tsc --noEmit && npm test && npm run lint` green
3. ☐ Live `/eval` on a real project produces `metrics/eval_<ts>/{summary.json,cells.jsonl,matrix.csv,meta.json}`
4. ☐ Frontend `/projects/<slug>/eval/<ts>` renders matrix
5. ☐ Cell click opens drilldown + can jump to review mode
6. ☐ `/compare <model>` from chat: runs flow, posts markdown delta, links to compare page
7. ☐ `/projects/<slug>/eval/compare?a=…&b=…` renders side-by-side
8. ☐ CSV download from matrix page opens correctly in Excel
9. ☐ Symmetry invariant green; all new tools have HTTP routes or are in `_HTTP_ONLY` with justification
10. ☐ Legacy `metrics/eval_<ts>.json` files still readable by `GET /eval/latest` and matrix page (or graceful "no per-cell data" empty state)
11. ☐ With `use_llm_judge=True`, cache populated at `.eval_judge_cache/`; second run with same pairs makes 0 provider calls
12. ☐ ROADMAP M12 row added with status ✅

## Risks / known unknowns

- **rapidfuzz `fuzz.ratio` threshold of 95**: may be too aggressive for short strings (3-4 chars). If T4 tests show false positives on real reviewed data, lower default to 90 OR make threshold proportional to string length. **Mitigation**: ship default 95, document `fuzzy_threshold` schema attr in T4, leave threshold tunable per-field.
- **dateparser performance**: dateparser is slow for large reviewed sets. Estimate: ~10ms per parse × 100 docs × 5 fields × 2 sides = ~10s overhead. Acceptable for lab; flag in T6 test.
- **CSV middle-dot `·` rendering**: confirmed valid in Excel UTF-8 CSV. If not opening cleanly on Windows-locale Excel, fallback to `__truth` / `__pred` (sklearn convention). **Mitigation**: T8 test verifies UTF-8 BOM written.
- **JSON schema validation for LLM judge response**: provider may not honor `response_schema` strictly. **Mitigation**: T5 tests already handle malformed response (returns L1 verdict).
- **Multi-entity ordering**: scoring pairs by index assumes order is meaningful. If reviewer/extractor disagree on ordering (e.g. line_items), pair-by-index penalizes both. **Mitigation**: out of scope; documented in CLAUDE.md hard rules already ("output contract: top-level array"). Same as current behavior.

## Out-of-scope follow-ups (post-M12)

- Per-cell evaluator-in-the-loop (user override judge verdict; data model accommodates it)
- Schema editor UI for `absent_policy` and `fuzzy_threshold` (currently set via `Edit prompts/{pid}.json`)
- Judge model selection from UI (env-only this round)
- Cross-project eval diff
- Stream matrix updates as `run_eval` progresses
- Bulk re-eval all historical metrics with new pipeline (no backfill this round)
