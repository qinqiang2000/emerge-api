# E2E Suite Repair — re-align Playwright specs with the M7 design-handoff UI

> **For agentic workers:** Use `superpowers:executing-plans` (or `superpowers:subagent-driven-development`) to work this task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** `cd frontend && npm run e2e` currently fails **all 5 specs**. None of the failures are caused by recent work (ToolStack collapse / Composer Enter fix, commits `e750f2c` / `196b35f` / `67c4fdf`) — the specs were written against the **pre-M7 UI** and the `m7-design-handoff-ui` merge rewrote the markup they target. Re-selector every spec so the suite is green against the current UI, then run it to confirm.

**Out of scope:** No product behavior changes. No new tests beyond what's needed to keep coverage equivalent. Don't "improve" the flows — just make the existing assertions reach the right elements. If a spec asserts something the new UI genuinely no longer does, note it and adjust the assertion to the closest current equivalent (don't delete the spec without flagging).

---

## Why each spec fails today (observed 2026-05-11)

| Spec | Failure | Root cause |
|---|---|---|
| `chat-layout.spec.ts` | `getByRole('button', { name: 'e2e-test' })` times out | Project name in the new sidebar (`FSSpine` / projects rail) renders as a clickable **row containing `StaticText`**, not a `<button>`. The seed *does* create a project named `e2e-test` (`backend/tests/e2e_seed.py`). |
| `publish-modal.spec.ts` | same `e2e-test` button timeout | same |
| `review-mode.spec.ts` | same `e2e-test` button timeout (then would need `sample.pdf` doc-list selector check) | same; also doc-list rows in the right rail / spine changed shape |
| `review-mode-evidence.spec.ts` | same `e2e-test` button timeout | same |
| `walking-skeleton.spec.ts` | `getByText('Projects')` → strict-mode violation (matches `~/projects/`, the `fs-head`, and the `main` eyebrow — 3 elements) | Old top-bar label "Projects" no longer exists; UI says `~/projects/` in several places |

**Already pre-staged (correct, but currently unreachable):** `chat-layout.spec.ts` and `walking-skeleton.spec.ts` were updated in commit `196b35f` to expand the new ToolStack before asserting plumbing tool names — `const toolStackHead = page.getByRole('button', { name: /Ran \d+ tool/ }); await toolStackHead.click()` — because consecutive plumbing tool calls now collapse into `Ran N tools ›`. That logic is right; it just never runs because the project-selection step above fails first. Keep it.

---

## Reference: what the current UI actually looks like

Take a real snapshot rather than trusting this section — but as orientation (from the 2026-05-11 dogfood, project `us-invoice`):

- **Projects rail (left):** `~/PROJECTS` header, then rows like `· us-invoice` then `/ 6` (doc count). The project name `us-invoice` is a `StaticText` inside a clickable row, **not** a button. Clicking the row selects the project. → e2e should locate the project by its text and click the row (or the nearest clickable ancestor), e.g. `page.getByText('e2e-test', { exact: true }).click()` or scope to the projects `<aside>`/`complementary` first.
- **After selecting:** top bar shows `<project>/ / schema · v<N> · frozen` and `watching docs/ · N files`. A second sidebar pane (`FSSpine`) appears with `docs/`, `reviewed/`, `versions/` trees; right rail (`ContextSurface`) shows `SCHEMA.JSON`, `DOCS/` (doc buttons with `REVIEWED` / `PENDING` badges — these *are* `button` role: `getByRole('button', { name: /sample\.pdf/ })` style still works for the right-rail doc list), and `METRICS/`.
- **Composer submit semantics (changed in `67c4fdf` — important for `chat-layout` / `walking-skeleton` / `publish-modal` which submit slash commands):**
  - Typing a full command name (`/extract`) **closes the autocomplete menu** (`showSlash = startsWith('/') && !completedCommand`).
  - Plain `Enter` then submits — so `textarea.fill('/extract'); textarea.press('Enter')` **works again** after the fix (it didn't before).
  - Partial command (`/ext`): plain `Enter` or `Tab` *picks* the active item → fills `/extract ` → menu closes → next `Enter` submits.
  - `Meta+Enter` / `Control+Enter` always submits, menu open or not — the most robust choice for e2e.
  - Do **not** press `Escape` in the composer — it clears the textarea (when menu closed it blurs).
- **ToolStack:** consecutive *plumbing* tool calls (`list_docs`, `extract_batch`, `create_project`, `read_documents`, …) render collapsed as a `<button>` named `Ran N tools ›` / `Ran 1 tool ›`. Expand it (`.click()`) before asserting individual tool names. **Rich-card tools** (`score`, `readiness_check`, `issue_api_key`, `start_job`) are *hoisted out* of the stack and render as their own blocks (`EvalCard` / `PublishStage` / `JobProgressCard`) — assert those directly, they're not inside any ToolStack.

---

## Verification protocol

- **Port hygiene:** Playwright's `webServer` spins up its own test-mode backend on `:8080` (`EMERGE_TEST_MODE=1 EMERGE_WORKSPACE_ROOT=./.tmp_workspace`, after `rm -rf` + `python -m tests.e2e_seed`) and a dev server on `:5172`. Both must be **free** before `npm run e2e`. If `:8080 is already used` → `lsof -ti :8080 | xargs kill`, then retry. (`reuseExistingServer: false` means it won't piggyback.)
- Run from `frontend/`: `npm run e2e` (it's `NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 playwright test`). For one spec at a time while iterating: `./node_modules/.bin/playwright test tests/e2e/walking-skeleton.spec.ts`.
- Use `--debug` or `page.pause()` sparingly; faster to add a `take_snapshot`-equivalent: temporarily `console.log(await page.content())` or use `playwright test --trace on` and inspect `test-results/.../trace.zip`.
- Iterate spec-by-spec; don't batch-edit blind.

---

## Tasks

- [ ] **Snapshot the current UI first.** Start the e2e webServers manually (or just `npm run dev` + a test-mode backend) and open `:5172`/`:5173`; capture the projects-rail markup, the doc-list rows, the review-mode layout, and the publish flow's inline `PublishStage` card. Write down the real selectors. Don't guess from this plan.
- [ ] **`walking-skeleton.spec.ts`** — replace `getByText('Projects')` with a stable anchor for "app loaded" (e.g. the projects rail header, or the composer textbox). Keep the ToolStack-expand step. Confirm `textarea.fill('extract core invoice info'); textarea.press('Enter')` submits (plain message, no slash → always submitted on Enter). Assert the stub agent_text + the expanded `create_project` / `extract_batch` names.
- [ ] **`chat-layout.spec.ts`** — fix the `e2e-test` project selection (click the row, not a `button`). Keep the ToolStack-expand step (`Ran N tools ›` → click → assert `list_docs` / `extract_batch`). Re-check the `[data-role="user-bubble"]` / `justify-end` assertion against current markup.
- [ ] **`review-mode.spec.ts`** — fix `e2e-test` selection; fix the `sample.pdf` doc-row selector (right-rail `DOCS/` buttons carry a `PENDING`/`REVIEWED` badge — `getByRole('button', { name: /sample\.pdf/ })` likely still works, verify); re-check the field-edit → save → badge-flip flow against the current review overlay.
- [ ] **`review-mode-evidence.spec.ts`** — fix `e2e-test` selection; re-check the `pX` evidence badge selector and the click-doesn't-crash assertion (the click-to-page jump uses the page-int `_evidence`; the seed injects `_evidence: [{invoice_number: 1, ...}]`).
- [ ] **`publish-modal.spec.ts`** — fix `e2e-test` selection; the publish flow renders an **inline** `PublishStage` card in the chat thread (not a dialog). Verify the `KEY MINTED` eyebrow / `STUB_KEY` plaintext-in-card / `key issued` redacted-trail / close-button assertions still match. Submitting `/publish`: `textarea.fill('/publish'); textarea.press('Enter')` should work post-fix (full command name → menu closed → Enter submits), but `Meta+Enter` is the safe fallback.
- [ ] **Green run.** `npm run e2e` → all 5 pass. If any flow genuinely changed (an assertion the new UI no longer satisfies), adjust to the closest equivalent and add a one-line `docs/design-decisions.md` note rather than silently dropping coverage.
- [ ] **Commit.** One commit, message scoped to "e2e: re-align specs with M7 design-handoff UI". Stage only the `tests/e2e/*.spec.ts` files (+ `docs/design-decisions.md` if a note was added).

---

## Notes / gotchas

- `playwright.config.ts` `baseURL` is `http://127.0.0.1:5172` and launches Chrome with `--proxy-server=direct://` (needed for SSE streaming). Don't change these.
- The seed (`backend/tests/e2e_seed.py`) creates project `e2e-test` with 2 schema fields, a `sample.pdf` draft (with `_evidence`), an `eval_gt.pdf` + a saved reviewed record. If a spec needs more seed data, extend the seed — don't fabricate it via the UI mid-test.
- `EMERGE_TEST_MODE=1` swaps in `app/api/routes/_test_stubs` for the chat route — that's why `/extract` / `/publish` produce deterministic tool_call + tool_result events without burning provider tokens. The stub's tool names and result shapes are the contract the e2e assertions key off; if they drifted from the real tools, that's a separate fix (flag it).
- Don't forget: a stale `backend/.tmp_workspace` is `rm -rf`'d by the webServer command on every run, so don't rely on its contents persisting between runs.
