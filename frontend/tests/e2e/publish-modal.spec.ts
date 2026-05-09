import { test, expect } from '@playwright/test'


// Drives the M3 publish flow against the test-stub chat route. The stub emits
// realistic tool_call + paired tool_result events for readiness_check /
// freeze_version / issue_api_key. The chat store should detect issue_api_key
// and route the plaintext into the reveal modal while leaving the chat
// events with only the prefix + short hash.
const STUB_KEY = 'ek_stubbedkey0123456789ABCDEF01234'
const STUB_PREFIX = 'ek_stubbed'

test('publish flow: modal pops with key, plaintext stays out of chat events', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('e2e-test')).toBeVisible({ timeout: 10_000 })
  await page.getByRole('button', { name: 'e2e-test' }).click()

  const textarea = page.getByRole('textbox')
  await textarea.fill('/publish')
  await textarea.press('Enter')

  // Modal pops via the issue_api_key tool_result branch in the chat store.
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible({ timeout: 10_000 })

  // Plaintext IS visible — but only inside the modal (Radix Portal at body).
  await expect(dialog.getByText(STUB_KEY)).toBeVisible()

  // Chat trail card shows the prefix + short hash, never the full plaintext.
  // KeyTrailCard renders `{prefix} ...hash {hash_short}` — both visible.
  await expect(page.getByText('key issued')).toBeVisible()
  await expect(page.getByText(/hash ffffff/)).toBeVisible()

  // Verify the chat-events region is plaintext-free. Modal content lives in a
  // Portal under <body>, so .font-body (MessageList wrapper) excludes it.
  const messageList = page.locator('.font-body').first()
  const chatText = (await messageList.textContent()) ?? ''
  expect(chatText).toContain(STUB_PREFIX)         // prefix is fine
  expect(chatText).not.toContain(STUB_KEY)        // full plaintext must NOT be here

  // Acknowledge to close. The modal is force-modal — Esc / click-outside are
  // disabled. Only the "我已保存" button dismisses. The button's aria-label is
  // "我已保存 — 关闭" (visible text differs slightly).
  await dialog.getByRole('button', { name: '我已保存 - 关闭' }).click()
  await expect(dialog).not.toBeVisible()

  // After close: the full plaintext is gone from the page entirely.
  await expect(page.getByText(STUB_KEY)).toHaveCount(0)
  // Trail card with prefix-only persists.
  await expect(page.getByText('key issued')).toBeVisible()
})
