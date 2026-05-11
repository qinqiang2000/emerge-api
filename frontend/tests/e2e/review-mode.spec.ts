// frontend/tests/e2e/review-mode.spec.ts
// M7: project selection is a sidebar row; the doc list lives in the right-rail
// ContextSurface as role="button" rows with an uppercase status badge.
import { test, expect } from '@playwright/test'

test('open a doc, edit a field, save, badge flips to reviewed', async ({ page }) => {
  await page.goto('/')

  // select the seeded project (clickable `.proj` row, not a <button>)
  const projRow = page.locator('.proj', { hasText: 'e2e-test' })
  await expect(projRow).toBeVisible({ timeout: 10_000 })
  await projRow.click()

  // right-rail doc list shows sample.pdf with a "pending" badge (rendered
  // uppercase by CSS — the accessible name is "sample.pdf PENDING")
  const docBtn = page.getByRole('button', { name: /sample\.pdf pending/i })
  await expect(docBtn).toBeVisible()

  // click the doc to enter review mode
  await docBtn.click()

  // FieldEditor renders: look for field name "invoice_number" in the .name span
  await expect(page.locator('.rev-fld .name', { hasText: 'invoice_number' })).toBeVisible({ timeout: 8_000 })

  // Find the corresponding .val contentEditable span (first row = invoice_number)
  const valSpan = page.locator('.rev-fld').first().locator('.val')
  await expect(valSpan).toBeVisible()

  // Clear and type a new value, then blur to commit the change
  await valSpan.click()
  await valSpan.fill('CONFIRMED-1')
  await valSpan.blur()

  // The review-bar save button is just labelled "save" now.
  const saveBtn = page.getByRole('button', { name: 'save', exact: true })
  await saveBtn.click()

  // wait for the save round-trip to finish (button reverts from "saving…"), then back out
  await expect(saveBtn).toBeEnabled({ timeout: 10_000 })
  await page.getByRole('button', { name: /back/i }).click()

  // doc list shows "reviewed" badge now
  await expect(page.getByRole('button', { name: /sample\.pdf reviewed/i })).toBeVisible()
})
