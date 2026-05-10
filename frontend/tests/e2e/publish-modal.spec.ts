import { test, expect } from '@playwright/test'


// Drives the M3/M7 publish flow against the test-stub chat route. The stub emits
// realistic tool_call + paired tool_result events for readiness_check /
// freeze_version / issue_api_key. The chat store detects issue_api_key
// and routes the plaintext into the in-thread PublishStage key card while leaving
// the chat events with only the prefix + short hash (redacted: true).
const STUB_KEY = 'ek_stubbedkey0123456789ABCDEF01234'
const STUB_PREFIX = 'ek_stubbed'

test('publish flow: key card appears inline, plaintext stays out of chat jsonl events', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('e2e-test')).toBeVisible({ timeout: 10_000 })
  await page.getByRole('button', { name: 'e2e-test' }).click()

  const textarea = page.getByRole('textbox')
  await textarea.fill('/publish')
  await textarea.press('Enter')

  // PublishStage key card renders inline in the chat thread (not a dialog).
  // It shows "KEY MINTED" eyebrow.
  await expect(page.getByText(/KEY MINTED/i)).toBeVisible({ timeout: 10_000 })

  // Plaintext IS visible — only inside the .pub-key card in the chat thread.
  await expect(page.getByText(STUB_KEY)).toBeVisible()

  // After the reveal card: the redacted trail line is also present.
  await expect(page.getByText('key issued')).toBeVisible()
  await expect(page.getByText(/hash ffffff/)).toBeVisible()

  // Verify the chat-events region contains STUB_PREFIX (trail) but NOT the
  // full plaintext key AFTER the close button is clicked.
  await page.getByText(/I've saved this key/i).click()

  // After close: plaintext is gone from the page entirely.
  await expect(page.getByText(STUB_KEY)).toHaveCount(0)
  // Trail card with prefix-only persists.
  await expect(page.getByText('key issued')).toBeVisible()
  await expect(page.getByText(STUB_PREFIX)).toBeVisible()
})
