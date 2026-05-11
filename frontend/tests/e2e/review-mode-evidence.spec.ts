// frontend/tests/e2e/review-mode-evidence.spec.ts
// Evidence badges are aria-label="jump to page N" buttons (.ev class).
import { test, expect } from '@playwright/test'

test('field with _evidence shows pX badge and click does not crash', async ({ page }) => {
  await page.goto('/')

  // select the seeded project (clickable `.proj` row, not a <button>)
  const projRow = page.locator('.proj', { hasText: 'e2e-test' })
  await expect(projRow).toBeVisible({ timeout: 10_000 })
  await projRow.click()

  // sample.pdf is the draft (with _evidence injected by the seeder)
  await page.getByRole('button', { name: /sample\.pdf pending/i }).click()

  // pN badge is rendered for both fields; strict-mode requires .first() when 2 match
  await expect(page.getByLabel('jump to page 1').first()).toBeVisible()
  // double-up: invoice_number AND total_amount each have a badge
  expect(await page.getByLabel('jump to page 1').count()).toBe(2)

  // clicking does not throw — the one-page fixture stays on "page 1 / 1"
  await page.getByLabel('jump to page 1').first().click()
  await expect(page.getByText(/page 1 \/ 1/)).toBeVisible()
})
