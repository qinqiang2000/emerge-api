// Targeted check: when project has 0 non-archived experiments, the tab strip
// is hidden entirely (no lonely ⭐ Active chip).
import { chromium } from '@playwright/test'
import fs from 'node:fs'

const OUT = new URL('./dogfood-out/', import.meta.url).pathname
fs.mkdirSync(OUT, { recursive: true })

const BASE = 'http://127.0.0.1:5173'

;(async () => {
  const browser = await chromium.launch({ headless: true })
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()

  // Pretend the us-invoice project has no experiments.
  await page.route('**/lab/projects/*/experiments*', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  )

  await page.goto(BASE, { waitUntil: 'networkidle' })
  await page.locator('.proj', { hasText: 'us-invoice' }).first().click()
  await page.waitForTimeout(500)
  await page.getByRole('button', { name: /Airbus Invoice\.pdf/i }).first().click()
  await page.waitForTimeout(1200)

  const tablistCount = await page.locator('.rev-bar [role="tablist"]').count()
  const activeTabCount = await page.locator('.rev-bar [role="tab"]', { hasText: /Active/i }).count()
  const spacerCount = await page.locator('.rev-bar > .spacer').count()
  const path = OUT + '10-no-experiments-no-tabstrip.png'
  await page.screenshot({ path })
  console.log('tablist:', tablistCount, ' ⭐Active chip:', activeTabCount, ' spacer:', spacerCount)
  console.log('screenshot →', path)
  if (tablistCount === 0 && activeTabCount === 0 && spacerCount === 1) {
    console.log('✅ tab strip hidden when no experiments; spacer fills the gap')
  } else {
    console.log('❌ unexpected: tablist or ⭐Active still rendered')
    process.exitCode = 1
  }
  await browser.close()
})()
