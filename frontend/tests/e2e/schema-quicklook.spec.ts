import { expect, test } from '@playwright/test'

// The shared e2e seed (backend/tests/e2e_seed.py) creates an "e2e-test" project
// with 2 schema fields (invoice_number, total_amount) and no frozen versions.
// We cover the schema-side entry points + close affordances + tab switch in this
// spec. The versions/vN entry point is exercised by FSSpine-quicklook.test.tsx
// at the unit level; the seed has no frozen version to click here.

test('quick-look: schema entry points + tab switch + close affordances', async ({ page }) => {
  await page.goto('/')

  const projRow = page.locator('.proj', { hasText: 'e2e-test' })
  await expect(projRow).toBeVisible({ timeout: 10_000 })
  await projRow.click()

  // ── Entry 1: right-rail ContextSurface Prompt-card title ─────────────────
  await expect(page.locator('.ctx-h', { hasText: /Prompt:/ })).toBeVisible()
  await page.locator('.ctx-h', { hasText: /Prompt:/ }).click()
  await expect(page.locator('.ql-sheet')).toBeVisible()
  await expect(page.locator('.ql-title')).toHaveText('prompts/active')

  // Prompt tab is default; both seeded fields render.
  await expect(page.locator('.ql-edit-name', { hasText: 'invoice_number' })).toBeVisible()
  await expect(page.locator('.ql-edit-name', { hasText: 'total_amount' })).toBeVisible()

  // Lineage row renders pr_baseline for a fresh project (M9.1 baseline lineage).
  await expect(page.locator('.ql-lineage')).toContainText('derived from:')

  // Switch to raw json tab — non-empty <pre> renders.
  await page.getByRole('button', { name: 'raw json' }).click()
  await expect(page.locator('.ql-raw')).toBeVisible()
  await expect(page.locator('.ql-raw')).toContainText('"name": "invoice_number"')

  // Close with Esc.
  await page.keyboard.press('Escape')
  await expect(page.locator('.ql-sheet')).toHaveCount(0)

  // ── Entry 2: left-rail FSSpine prompts/ active row ───────────────────────
  // Expand prompts/ group first (closed by default in M9.2).
  await page.locator('.branch.dir', { hasText: 'prompts/' }).click()
  // Click the active Baseline prompt row.
  await page.locator('.branch.file', { hasText: 'Baseline' }).click()
  await expect(page.locator('.ql-sheet')).toBeVisible()
  await expect(page.locator('.ql-title')).toHaveText('prompts/active')

  // Footer hint (notes-vs-review) is present.
  await expect(page.locator('.ql-footer')).toContainText('notes + field descriptions go into the prompt')
  await expect(page.locator('.ql-footer')).toContainText('AutoResearch')

  // Close with scrim click (click outside the sheet body).
  await page.locator('[data-testid="ql-scrim"]').click({ position: { x: 10, y: 10 } })
  await expect(page.locator('.ql-sheet')).toHaveCount(0)
})
