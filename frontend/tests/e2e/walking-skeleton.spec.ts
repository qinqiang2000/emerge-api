import { test, expect } from '@playwright/test'

test('drag a PDF and submit chat — stubbed flow', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('Projects')).toBeVisible()

  // type a chat message and hit Enter
  const textarea = page.getByRole('textbox')
  await textarea.fill('extract core invoice info')
  await textarea.press('Enter')

  // expect the stub agent_text to appear
  await expect(page.getByText('Stub run complete')).toBeVisible({ timeout: 10_000 })

  // expect tool-call cards
  await expect(page.getByText('create_project')).toBeVisible()
  await expect(page.getByText('extract_batch')).toBeVisible()
})
