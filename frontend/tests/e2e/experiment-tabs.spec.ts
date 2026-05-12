// frontend/tests/e2e/experiment-tabs.spec.ts
// M9.3: attach experiment tab, switch shows experiment extract read-only, save is gated.
import { expect, test } from '@playwright/test'

test('attach experiment to review tab, switch shows experiment extract read-only, save is gated', async ({ page }) => {
  await page.goto('/')

  // Select the seeded project
  const projRow = page.locator('.proj', { hasText: 'e2e-test' })
  await expect(projRow).toBeVisible({ timeout: 10_000 })
  await projRow.click()

  // The FSSpine experiments/ group is visible and shows the seeded experiment
  const experimentsDir = page.locator('.branch.dir', { hasText: 'experiments/' })
  await expect(experimentsDir).toBeVisible()
  await experimentsDir.click()  // expand
  await expect(page.locator('.branch.file', { hasText: 'try gemma' })).toBeVisible()

  // Open review on the seeded doc (the one that has the experiment extract)
  const docBtn = page.getByRole('button', { name: /sample\.pdf pending/i })
  await expect(docBtn).toBeVisible()
  await docBtn.click()

  // The experiment tab strip is visible (experimentList.length > 0, so it renders)
  await expect(page.getByRole('tablist')).toBeVisible({ timeout: 8_000 })

  // Save button is enabled on ⭐ Active tab
  const saveBtn = page.getByRole('button', { name: 'save', exact: true })
  await expect(saveBtn).toBeEnabled()

  // [+] popover lists the seeded experiment — aria-label="+"
  await page.locator('[aria-label="+"]').click()
  const popoverItem = page.getByRole('menuitem', { name: /try gemma/i })
  await expect(popoverItem).toBeVisible()
  await popoverItem.click()

  // Experiment tab appears
  const expTab = page.getByRole('tab', { name: /try gemma/i })
  await expect(expTab).toBeVisible()
  await expTab.click()

  // The tab content now shows the experiment's value (FROM_EXPERIMENT)
  await expect(page.locator('.rev-fld', { hasText: 'FROM_EXPERIMENT' })).toBeVisible({ timeout: 6_000 })
  // The active draft value (DRAFT-1) is not shown
  await expect(page.locator('.rev-fld', { hasText: 'DRAFT-1' })).toHaveCount(0)

  // The .val span is contentEditable="false" (read-only) on this experiment tab
  const expValue = page.locator('.rev-fld', { hasText: 'FROM_EXPERIMENT' })
    .locator('.val[contenteditable]')
  await expect(expValue).toHaveAttribute('contenteditable', 'false')

  // Save is disabled on experiment tab (canSave=false when readOnly)
  await expect(saveBtn).toBeDisabled()

  // Switch back to ⭐ Active
  await page.getByRole('tab', { name: /Active/i }).click()
  // Active tab shows the draft value
  await expect(page.locator('.rev-fld', { hasText: 'DRAFT-1' })).toBeVisible()
  // Save re-enabled
  await expect(saveBtn).toBeEnabled()
})
