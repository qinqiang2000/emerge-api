import { expect, test } from '@playwright/test'

test('chat layout: user bubble right-aligned, agent left, consecutive tools grouped', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('e2e-test')).toBeVisible({ timeout: 10_000 })
  await page.getByRole('button', { name: 'e2e-test' }).click()

  const textarea = page.getByRole('textbox')
  await textarea.fill('/extract')
  await textarea.press('Enter')

  await expect(page.getByText('Running batch extract...')).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText('list_docs')).toBeVisible()
  await expect(page.getByText('extract_batch')).toBeVisible()
  await expect(page.locator('strong', { hasText: 'Done.' })).toBeVisible()

  const userBubble = page.locator('[data-role="user-bubble"]')
  await expect(userBubble).toBeVisible()
  const parentClass = await userBubble.evaluate(el => (el.parentElement as HTMLElement).className)
  expect(parentClass).toContain('justify-end')
})
