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

  // Plumbing tool calls now collapse into a ToolStack ("Ran N tools ›");
  // expand it to assert the tool names. See docs/design-decisions.md 2026-05-11.
  const toolStackHead = page.getByRole('button', { name: /Ran \d+ tool/ })
  await expect(toolStackHead).toBeVisible()
  await toolStackHead.click()
  await expect(page.getByText('create_project')).toBeVisible()
  await expect(page.getByText('extract_batch')).toBeVisible()
})
