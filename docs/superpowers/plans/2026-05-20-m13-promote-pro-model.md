> ## ❌ REVERTED 2026-05-20
>
> This milestone was reverted same-day. The framing was wrong: Pro
> (`gemini-pro-latest`) is the **labeler tier** (per-project
> `labeler_model`, runs once per doc for `_pending/`), not the
> production **active extract tier** (which stays Flash for cost
> reasons — `/v1/{pid}/extract` runs thousands of times). Promote
> reverted: `active_model_id` back to `m_default`, experiment status
> back to `ran`, `predictions/_draft/` re-populated via flash batch
> extract. Saved as `feedback_pro_is_labeler_flash_is_active.md`
> memory. Next move: separate plan to `/compare` flash variants
> (flash-2.5 vs flash-2.0 vs flash-1.5 / equivalent-tier rivals).

# M13 — promote gemini-pro-latest + residual field triage

> **Date:** 2026-05-20
> **Project:** `默沙东_小票`
> **Predecessor:** M12 (eval-as-module) dogfood produced apples-to-apples comparison N=20
> **Successor:** TBD — likely GT cleanup pass + L2 normalize-judge tuning, then field-targeted /improve

## Context

M12 dogfood on `默沙东_小票` (20 reviewed docs) revealed:

| | flash (baseline) | pro (candidate `ex_06aikys07r8l`) | Δ |
|---|---|---|---|
| macro_f1 | 0.502 | **0.849** | +69 % |
| doc_accuracy | 0.050 | **0.400** | ×8 |
| coverage | 20 | 20 | — |

`ex_06aikys07r8l` = `pr_baseline × m_geminipro`. Zero per-field regressions vs flash. Apples-to-apples evidence is conclusive.

Per `eval-first` rule (compare model BEFORE schema): lock model switch first, defer schema/AutoResearch until the new baseline is set.

## Goal

Promote `ex_06aikys07r8l` to active and triage the residual weak fields (`seller_name 0.71` / `items 0.83` / `remarks 0.47`) by looking at `cells.jsonl` — decide which residual is worth `/improve`, which is GT noise, which is L2 normalize-judge territory.

## Out of scope

- **M12 robustness gap** (single-doc failure fails whole batch in `run_experiment_eval`; pro >120 s on dense docs hits `provider/google.py` default timeout). Separate M12.x followup. Empirically: `00cb6a2b.jpg` is the smoking gun — already in `reviewed/` but not in the experiment's cached predictions, so promote will leave its `_draft/` slot empty. Acceptable for M13 (eval still has coverage 20 from the other docs).
- Cross-project rollout. Other projects keep `m_default`.
- Schema/AutoResearch round on residual fields. Decision happens in T3 based on `cells.jsonl`; execution (if warranted) is M13.x.

## Tasks

### T1 — Pre-flight verification

- Confirm `ex_06aikys07r8l` status = `ran` and references the right pair (`pr_baseline × m_geminipro`).
- Confirm experiment has 20 cached predictions, incl. `02ba18df.pdf` (11-entity Thai/EN PDF — promote needs to carry it intact).
- Note: `00cb6a2b.jpg` is in `reviewed/` (21st doc, added post-experiment) but NOT in the experiment's cached predictions — after promote, `_draft/00cb6a2b.jpg.json` will be missing. Do NOT re-extract it now (M12.x robustness gap). Eval will report coverage=20.

### T2 — Promote

- `POST /lab/projects/默沙东_小票/experiments/ex_06aikys07r8l/promote`
- Verify response 200; verify `project.json.active_model_id = "m_geminipro"`; verify `_draft/` has exactly the 20 experiment-cached files.
- Verify `_draft/02ba18df.pdf.json` still has 11 entities.

### T3 — Verify eval matches candidate

- `POST /lab/projects/默沙东_小票/score` (no body — runs against active).
- `GET /lab/projects/默沙东_小票/evals/latest`.
- Expected: `macro_f1 ≈ 0.849`, `doc_accuracy ≈ 0.400`, coverage = 20. Per-field numbers should match the candidate eval (`metrics/eval_2026-05-20T07-21-06Z/summary.json`) within rounding.

### T4 — Residual field triage (analytic, no code change)

Cells.jsonl already pulled and analyzed. Findings:

**`seller_name` (F1 0.71, 10 wrong cells):**
- 6/10 are `02ba18df.pdf` entities where model includes Thai jurisdictional suffix (`ท่าเรือแหลมฉบัง`) or English corporate suffix (`Limited`, `CO.,LTD.`) — GT dropped them. Reasonable model behavior; GT inconsistent.
- 2 are Chinese branch suffix (`西塔老太太（济南世茂店）` vs GT `西塔老太太`). Same GT-policy noise.
- 1 is real OCR-level miss (`蚝` vs `蛙` first char).
- 1 is real missing (hotel name `桂林会展国际酒店` → None).
- **Verdict:** ~80 % GT noise / policy inconsistency, ~20 % real misses. NOT a clean `/improve` target — schema description tweak ("preserve original company name verbatim including jurisdiction/branch suffixes" vs "drop them") would chase a GT that doesn't yet have a policy. **Defer pending GT cleanup pass.**

**`items` (F1 0.83, 5 substantive wrong):**
- 2 are character variants (`蕃茄`/`番茄`, `●` separator dropped) — model normalization vs GT verbatim. L2 normalize-judge territory.
- 1 is full-width vs half-width parens (`（济南）` vs `(济南)`) + float vs int (`268.0` vs `268`). L2 normalize-judge territory.
- 2 are Thai item-name prefix difference (`ค่าลานตู้/ LIFT ON / OFF` vs `LIFT ON / OFF`). Could go either way.
- 1 real miss: `00b1aef5.jpg` unit_price drops on multiple items (model returned None for unit_price when GT had numbers).
- **Verdict:** ~70 % normalize-judge / typography noise, ~30 % real unit_price extraction miss. L2 normalize-judge improvements (M12.x candidate) would close most of the gap; `/improve` description tweak might help the unit_price miss but the payoff is small.

**`remarks` (F1 0.47, 24 wrong cells):**
- ~14/24 are `absent_both` (pred=None, truth=None) — scoring artifact, not model error.
- 3 real missing (GT had remarks, model returned None).
- 4 spurious (model invented remarks, GT left blank).
- 2 Thai wrong (model returned full sentence including invoice ref, GT extracted only the ref number).
- **Verdict:** ~60 % score-math noise, ~30 % GT-policy inconsistency on "what counts as a remark", ~10 % real misses. NOT an `/improve` target — first fix the score-math (`absent_both` → exclude from F1 denominator), then look at the rest. **Defer to M12.x.**

**Decision:**
- **No `/improve` in M13.** The residual gap on all three fields is dominated by GT noise + scoring artifacts that AutoResearch can't fix and shouldn't be pointed at.
- Open follow-up: GT cleanup pass on `默沙东_小票` reviewed (seller_name jurisdictional/branch policy, remarks "what counts" policy) — user-driven, not a milestone.
- Open follow-up (M12.x candidate): L2 normalize-judge improvements (full-width parens, bullet separators, float/int coercion, `absent_both` exclusion).

### T5 — ROADMAP closeout + demo line

- Append M13 row to ROADMAP status table.
- Demo-ready one-liner (for client / docs):
  > **默沙东_小票 项目从 macro_f1 0.50 提升到 0.85（+69 %），doc accuracy 从 5 % 提升到 40 %（×8），通过一次 model switch（gemini-flash → gemini-pro-latest）+ candidate experiment promote 完成，无需 schema 改动。**

## Hard rules respected

- Experiments NEVER auto-promote — `promote_experiment` is the explicit user-mediated path. ✅
- `reviewed/` untouched. ✅
- Publish fast-path 0 改动 — `versions/`, `/v1/{pid}/extract` not touched. ✅
- Agent brain ↔ Extract LLM separation — promote flips Extract LLM only; SDK Anthropic locked. ✅
- No `/improve` blind-fire — `cells.jsonl` distribution analyzed first. ✅ (eval-first rule)

## Test footprint

No code changes. M13 is a pure operations milestone (promote + analyze + document). Existing test suite unchanged.
