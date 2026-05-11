import { test, expect } from '@playwright/test'


// Drives the M3/M7 publish flow against the test-stub chat route. The stub emits
// realistic tool_call + paired tool_result events for readiness_check /
// freeze_version / issue_api_key. The chat store detects issue_api_key
// and routes the plaintext into the in-thread PublishStage key card while leaving
// the chat events with only the prefix + short hash (redacted: true).
//
// M7 note: the key card and the redacted trail are the SAME inline PublishStage
// card in two states — the trail only appears AFTER the one-time reveal is
// closed (not alongside it like the pre-M7 dialog+trail split).
// See docs/design-decisions.md 2026-05-12.
const STUB_KEY = 'ek_stubbedkey0123456789ABCDEF01234'
const STUB_PREFIX = 'ek_stubbed'

test('publish flow: key card appears inline, plaintext stays out of chat jsonl events', async ({ page }) => {
  await page.goto('/')

  // select the seeded project (clickable `.proj` row, not a <button>)
  const projRow = page.locator('.proj', { hasText: 'e2e-test' })
  await expect(projRow).toBeVisible({ timeout: 10_000 })
  await projRow.click()

  const textarea = page.getByRole('textbox')
  await textarea.fill('/publish')
  await textarea.press('Enter')

  // PublishStage key card renders inline in the chat thread (not a dialog).
  // It shows the "KEY MINTED" eyebrow and the one-time plaintext key.
  await expect(page.getByText(/KEY MINTED/i)).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText(STUB_KEY)).toBeVisible()

  // Close the reveal — the card collapses to a redacted trail (prefix + short hash).
  await page.getByRole('button', { name: /I've saved this key/i }).click()

  // After close: the plaintext is gone from the page entirely.
  await expect(page.getByText(STUB_KEY)).toHaveCount(0)
  // The redacted trail card with prefix-only + short hash persists.
  await expect(page.getByText('key issued')).toBeVisible()
  await expect(page.getByText(STUB_PREFIX)).toBeVisible()
  await expect(page.getByText(/hash ffffff/)).toBeVisible()
})
