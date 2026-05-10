// frontend/tests/e2e/review-mode.spec.ts
// Updated for T11 new DOM structure — contentEditable .val spans replace labeled inputs.
import { test, expect } from '@playwright/test'

test('open a doc, edit a field, save, badge flips to reviewed', async ({ page }) => {
  await page.goto('/')

  // wait for project to load + click it
  await expect(page.getByText('e2e-test')).toBeVisible({ timeout: 10_000 })
  await page.getByRole('button', { name: 'e2e-test' }).click()

  // doc list shows up in right pane with "draft" badge
  await expect(page.getByText('sample.pdf')).toBeVisible()
  await expect(page.getByText('draft')).toBeVisible()

  // click the doc to enter review mode
  await page.getByRole('button', { name: /sample\.pdf/ }).click()

  // FieldEditor renders: look for field name "invoice_number" in the .name span
  await expect(page.locator('.rev-fld .name', { hasText: 'invoice_number' })).toBeVisible({ timeout: 8_000 })

  // Find the corresponding .val contentEditable span (first one = invoice_number field row)
  const valSpan = page.locator('.rev-fld').first().locator('.val')
  await expect(valSpan).toBeVisible()

  // Clear and type a new value
  await valSpan.click()
  await valSpan.fill('CONFIRMED-1')
  // Trigger blur to commit the change
  await valSpan.blur()

  await page.getByRole('button', { name: /save reviewed/i }).click()

  // wait for save to complete, then back out
  await expect(page.getByRole('button', { name: /save reviewed/i })).toBeEnabled({ timeout: 10_000 })
  await page.getByRole('button', { name: /back/i }).click()

  // doc list shows "reviewed" badge now
  await expect(page.getByRole('button', { name: /sample\.pdf reviewed/ })).toBeVisible()
})
