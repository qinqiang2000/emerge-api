import { expect, test } from '@playwright/test'

test('chat layout: user line distinct from agent, consecutive plumbing tools grouped', async ({ page }) => {
  await page.goto('/')

  // Select the seeded project. In the M7 sidebar (FSSpine) the project name is
  // a clickable row (`.proj`), not a <button>.
  const projRow = page.locator('.proj', { hasText: 'e2e-test' })
  await expect(projRow).toBeVisible({ timeout: 10_000 })
  await projRow.click()

  const textarea = page.getByRole('textbox')
  await textarea.fill('/extract')
  await textarea.press('ControlOrMeta+Enter')

  await expect(page.getByText('Running batch extract...')).toBeVisible({ timeout: 10_000 })

  // Plumbing tool calls now collapse into a ToolStack ("Ran N tools ›");
  // expand it to assert the tool names. See docs/design-decisions.md 2026-05-11.
  const toolStackHead = page.getByRole('button', { name: /Ran \d+ tool/ })
  await expect(toolStackHead).toBeVisible()
  await toolStackHead.click()
  await expect(page.getByText('list_docs')).toBeVisible()
  await expect(page.getByText('extract_batch')).toBeVisible()
  await expect(page.locator('strong', { hasText: 'Done.' })).toBeVisible()

  // The terminal-style chat renders the user line as `.msg.user` (italic,
  // smart-quoted via CSS ::before/::after) — distinct from agent turns. The
  // pre-M7 right-aligned "bubble" layout is gone. See docs/design-decisions.md 2026-05-12.
  const userMsg = page.locator('.msg.user')
  await expect(userMsg).toBeVisible()
  await expect(userMsg).toHaveText('/extract')
})
