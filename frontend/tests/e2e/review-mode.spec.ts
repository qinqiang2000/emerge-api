// frontend/tests/e2e/review-mode.spec.ts
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

  // FieldEditor renders: invoice_number with value DRAFT-1
  const invoiceInput = page.getByLabel(/invoice_number/)
  await expect(invoiceInput).toHaveValue('DRAFT-1')

  // edit and save
  await invoiceInput.fill('CONFIRMED-1')
  await page.getByRole('button', { name: /save reviewed/i }).click()

  // wait for save to complete, then back out
  await expect(page.getByRole('button', { name: /save reviewed/i })).toBeEnabled({ timeout: 10_000 })
  await page.getByRole('button', { name: /back/i }).click()

  // doc list shows "reviewed" badge now
  await expect(page.getByRole('button', { name: /sample\.pdf reviewed/ })).toBeVisible()
})
