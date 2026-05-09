// frontend/tests/e2e/review-mode-evidence.spec.ts
import { test, expect } from '@playwright/test'

test('field with _evidence shows pX badge and click does not crash', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByText('e2e-test')).toBeVisible({ timeout: 10_000 })
  await page.getByRole('button', { name: 'e2e-test' }).click()

  // sample.pdf is the draft (with _evidence injected by seeder)
  await page.getByRole('button', { name: /sample\.pdf/ }).click()

  // pN badge is rendered for both fields; strict-mode requires .first() when 2 match
  await expect(page.getByLabel('jump to page 1').first()).toBeVisible()
  // double-up: invoice_number AND total_amount each have a badge
  expect(await page.getByLabel('jump to page 1').count()).toBe(2)

  // clicking does not throw — page indicator stays at "1 / 1" since the fixture is one page
  await page.getByLabel('jump to page 1').first().click()
  await expect(page.getByText('1 / 1')).toBeVisible()
})
