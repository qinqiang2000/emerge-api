import { expect, test } from '@playwright/test'

test('chat history popover: lists the active project sessions; new-chat → empty hero; switch round-trips', async ({ page }) => {
  await page.goto('/')

  const projRow = page.locator('.proj', { hasText: 'e2e-test' })
  await expect(projRow).toBeVisible({ timeout: 10_000 })
  await projRow.click()

  // The active project row shows a status dot (this seed project is "draft").
  await expect(page.locator('.proj.active .status-dot')).toBeVisible()

  // FS tree: docs/ is open by default, reviewed/ is collapsed.
  await expect(page.locator('.branch.dir', { hasText: 'docs/' })).toBeVisible()
  const reviewedDir = page.locator('.branch.dir', { hasText: 'reviewed/' })
  await expect(reviewedDir).toBeVisible()
  const docFile = page.locator('.branch.file', { hasText: 'sample.pdf' })
  await expect(docFile).toBeVisible()
  await page.locator('.branch.dir', { hasText: 'docs/' }).click()
  await expect(docFile).toHaveCount(0)
  await page.locator('.branch.dir', { hasText: 'docs/' }).click()  // re-open

  // Open the chat-history popover.
  await page.getByLabel('Chat history').click()
  await expect(page.locator('.hist-pop')).toBeVisible()
  await expect(page.locator('.hist-pop .h-hd .lab')).toHaveText('history')
  await expect(page.locator('.hist-pop .h-hd .scope')).toHaveText('e2e-test')
  const seededRow = page.locator('.hist-pop .h-row', { hasText: 'weak fields' })
  await expect(seededRow).toBeVisible()
  await expect(seededRow.locator('.kind')).toHaveText('tune')

  // Switching to it loads the seeded events into the conversation.
  await seededRow.click()
  await expect(page.locator('.hist-pop')).toHaveCount(0)  // popover closed on switch
  await expect(page.getByText('Seeded session for the e2e.')).toBeVisible()

  // New chat → events cleared. (EmptyHero only renders for a project with no
  // docs/fields; this seed has both, so .conv-inner stays mounted but empty.)
  await page.getByLabel('New chat').click()
  await expect(page.getByText('Seeded session for the e2e.')).toHaveCount(0)
  await expect(page.locator('.conv-inner .msg')).toHaveCount(0)
})
