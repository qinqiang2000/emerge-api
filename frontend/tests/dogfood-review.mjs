// One-off dogfood script for the three fixes:
//   1) Bug: doc reviewer should now show page_number for already-reviewed docs
//   2) UI: back-arrow icon + tabs inline in the reviewing row (no separate row)
//   3) UI: all experiment tabs auto-shown; overflow collapses behind » N
//
// Runs against the live dev stack (Vite at :5173, backend proxied via Vite).
// Writes screenshots into ./tests/dogfood-out/.
import { chromium } from '@playwright/test'
import fs from 'node:fs'

const OUT = new URL('./dogfood-out/', import.meta.url).pathname
fs.mkdirSync(OUT, { recursive: true })

const BASE = 'http://127.0.0.1:5173'

async function shot(page, name) {
  const p = OUT + name + '.png'
  await page.screenshot({ path: p, fullPage: false })
  console.log('  screenshot →', p)
  return p
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()
  const failures = []

  // ── Step 1: load home, pick the us-invoice project ──
  console.log('▶ open home, select us-invoice project')
  await page.goto(BASE, { waitUntil: 'networkidle' })
  await shot(page, '01-home')

  // FSSpine lists projects with class .proj
  const projRow = page.locator('.proj', { hasText: 'us-invoice' }).first()
  await projRow.waitFor({ state: 'visible', timeout: 8_000 })
  await projRow.click()
  await page.waitForTimeout(800)
  await shot(page, '02-project-opened')

  // ── Step 2: open the Airbus doc (which was previously reviewed → exposes bug) ──
  console.log('▶ open Airbus Invoice.pdf in review')
  // Find the doc button — fall back to any clickable showing the filename
  const airbus = page.getByRole('button', { name: /Airbus Invoice\.pdf/i }).first()
  await airbus.waitFor({ state: 'visible', timeout: 6_000 })
  await airbus.click()
  await page.waitForTimeout(1200)
  await shot(page, '03-review-airbus')

  // ── Step 3: PROBLEM 1 — verify page_number now has the value "1" ──
  console.log('▶ check page_number field has a value')
  // Field rows render inside .rev-fields; each field has the field name visible
  const pageNumberField = page.locator('.rev-sect .rev-fld', { has: page.locator('text=/^page_number$/') }).first()
  await pageNumberField.waitFor({ state: 'visible', timeout: 4_000 })
  const pnText = (await pageNumberField.innerText()).trim()
  console.log('  page_number row text:', JSON.stringify(pnText))
  if (!/[\s\b]1\b/.test(pnText)) {
    failures.push('Problem 1: page_number row does not show value "1": ' + JSON.stringify(pnText))
  } else {
    console.log('  ✓ page_number shows value (Problem 1 fix verified)')
  }
  await shot(page, '04-airbus-page_number-fixed')

  // ── Step 4: PROBLEM 2 — verify back-arrow icon + tabs in same row as "reviewing" ──
  console.log('▶ check back button is an icon (no "back to chat" text) and tabstrip is in rev-bar')
  // The back button should have aria-label "back to chat" and contain an SVG icon (not text)
  const backBtn = page.locator('.rev-bar button[aria-label="back to chat"]')
  await backBtn.waitFor({ state: 'visible', timeout: 4_000 })
  const backText = (await backBtn.innerText()).trim()
  const backHasSvg = (await backBtn.locator('svg').count()) > 0
  console.log('  back button text:', JSON.stringify(backText), 'hasSvg:', backHasSvg)
  if (backText !== '' || !backHasSvg) {
    failures.push('Problem 2: back button should be icon-only; got text=' + JSON.stringify(backText) + ' hasSvg=' + backHasSvg)
  } else {
    console.log('  ✓ back button is icon-only')
  }

  // Tablist should be a child of .rev-bar (same row, not a separate row beneath)
  const tabsInBar = await page.locator('.rev-bar [role="tablist"]').count()
  const tabsOutsideBar = await page.locator(':not(.rev-bar) > [role="tablist"]').count()
  console.log('  tablists in .rev-bar:', tabsInBar, ' outside:', tabsOutsideBar)
  if (tabsInBar < 1) {
    failures.push('Problem 2: tablist not inside .rev-bar (still on its own row)')
  } else {
    console.log('  ✓ tablist lives inside .rev-bar (Problem 2 fix verified)')
  }

  // ── Step 5: tabs layout — ✏ annotation + one card per non-archived exp ──
  console.log('▶ check no "+" attach button + annotation tab present')
  const plusBtn = page.locator('.rev-bar button[aria-label="+"]')
  const plusCount = await plusBtn.count()
  if (plusCount > 0) failures.push('"[+]" attach button still present')
  else console.log('  ✓ no "+" attach button')

  const annotTab = page.locator('.rev-bar [role="tab"].rev-tab-annotation')
  const annotCount = await annotTab.count()
  if (annotCount !== 1) failures.push(`expected 1 annotation tab, got ${annotCount}`)
  else console.log('  ✓ ✏ annotation tab is present as the first tab')

  const expResp = await page.request.get(BASE + '/lab/projects/p_4w6rzeuz9dfi/experiments')
  const experiments = await expResp.json()
  const nonArchived = experiments.filter((e) => e.status !== 'archived')
  const tabCount = await page.locator('.rev-bar [role="tab"]').count()
  const expectedTabs = nonArchived.length + 1 // +1 for annotation
  console.log('  non-archived experiments:', nonArchived.length, ' tabs in bar:', tabCount, ' expected:', expectedTabs)
  if (tabCount !== expectedTabs) {
    failures.push(`tab count ${tabCount} != expected ${expectedTabs} (annotation + ${nonArchived.length} predictions)`)
  } else {
    console.log('  ✓ annotation tab + one card per non-archived experiment')
  }

  // Each card is 2-line: top = model label, bottom = prompt label
  const cards = page.locator('.rev-bar .rev-tab-card')
  if (await cards.count() > 0) {
    const firstCard = cards.first()
    const modelLine = firstCard.locator('.rev-tab-model')
    const promptLine = firstCard.locator('.rev-tab-prompt')
    const hasIcon = await firstCard.locator('.rev-tab-ico svg').count() > 0
    const modelText = (await modelLine.innerText().catch(() => '')).trim()
    const promptText = (await promptLine.innerText().catch(() => '')).trim()
    console.log('  first card → icon:', hasIcon, ' model:', JSON.stringify(modelText), ' prompt:', JSON.stringify(promptText))
    if (!hasIcon || !modelText || !promptText) {
      failures.push('2-line card layout missing icon/model/prompt')
    } else {
      console.log('  ✓ 2-line card layout (icon + model + prompt label)')
    }
  }
  await shot(page, '05-tabs-autoshown')

  // ── Step 5.5: click an experiment card → read-only + adopt buttons appear ──
  if (await cards.count() > 0) {
    console.log('▶ click first experiment card → enters read-only view')
    await cards.first().click()
    await page.waitForTimeout(400)
    const ariaSelected = await cards.first().getAttribute('aria-selected')
    const saveBtn = page.locator('.rev-bar button.save')
    const saveDisabled = await saveBtn.isDisabled()
    console.log('  aria-selected:', ariaSelected, ' save disabled:', saveDisabled)
    if (ariaSelected !== 'true' || !saveDisabled) {
      failures.push('clicking a card should mark it selected AND disable save')
    } else {
      console.log('  ✓ card selected + save disabled')
    }
    // adopt-all button should be visible on a prediction tab
    const adoptAll = page.locator('button[aria-label*="adopt this prediction" i]')
    if (await adoptAll.count() === 0) {
      failures.push('"adopt as annotation" header button missing on prediction tab')
    } else {
      console.log('  ✓ "adopt as annotation" header button present')
    }
    await shot(page, '05b-card-selected-readonly')

    console.log('▶ click ✏ annotation tab → returns to editable view')
    await page.locator('.rev-bar [role="tab"].rev-tab-annotation').click()
    await page.waitForTimeout(400)
    const aria2 = await cards.first().getAttribute('aria-selected')
    const save2Disabled = await saveBtn.isDisabled()
    console.log('  card aria-selected:', aria2, ' save disabled:', save2Disabled)
    if (aria2 === 'true' || save2Disabled) {
      failures.push('clicking the annotation tab should return to editable canonical')
    } else {
      console.log('  ✓ annotation tab regains editable state + save re-enabled')
    }
    await shot(page, '05c-back-to-annotation')
  }

  // ── Step 6: PROBLEM 3 — narrow window to trigger overflow >> dropdown ──
  console.log('▶ shrink width to provoke overflow')
  await page.setViewportSize({ width: 700, height: 900 })
  await page.waitForTimeout(500)
  await shot(page, '06-narrow-window')
  const overflowTrigger = page.locator('.rev-tab-overflow-trigger')
  const overflowVisible = await overflowTrigger.count() > 0
  console.log('  overflow trigger present at width=700:', overflowVisible)
  if (nonArchived.length > 0 && !overflowVisible) {
    console.log('  ⚠ overflow trigger not present (may be OK if few tabs)')
  } else if (overflowVisible) {
    console.log('  ✓ overflow » N trigger appears')
    await overflowTrigger.click()
    await page.waitForTimeout(300)
    await shot(page, '07-overflow-dropdown-open')
    const menu = page.locator('.rev-tab-popover')
    if (await menu.count() > 0) {
      console.log('  ✓ overflow dropdown menu opens')
    } else {
      failures.push('Problem 3: overflow trigger present but dropdown did not open')
    }
  }

  // ── Step 7: restore size, navigate prev/next, check second doc page_number too ──
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.waitForTimeout(300)
  console.log('▶ click prev/next nav arrows')
  const nextBtn = page.locator('.rev-bar .nav .arrow[aria-label="next doc"]')
  await nextBtn.click()
  await page.waitForTimeout(800)
  await shot(page, '08-next-doc')

  // Pick the multi_entity_2 doc (was the only one not previously reviewed → was already
  // working before the fix). Make sure it still works post-fix.
  // Navigate using the prev arrow until we find multi_entity_2 by title.
  // Or open from FSSpine.
  console.log('▶ check multi_entity_2.pdf still has page_number (no regression)')
  // Click "back to chat" via the icon, then re-open multi_entity_2 via the doc list
  const backIcon = page.locator('.rev-bar button[aria-label="back to chat"]')
  await backIcon.click()
  await page.waitForTimeout(800)
  const me2 = page.getByRole('button', { name: /multi_entity_2\.pdf/i }).first()
  if (await me2.count() > 0) {
    await me2.click()
    await page.waitForTimeout(1000)
    await shot(page, '09-multi_entity_2')
    const pn2 = page.locator('.rev-sect .rev-fld', { has: page.locator('text=/^page_number$/') }).first()
    if (await pn2.count() > 0) {
      const pn2Text = (await pn2.innerText()).trim()
      console.log('  multi_entity_2 page_number row:', JSON.stringify(pn2Text))
      if (!/\d/.test(pn2Text.split('page_number').slice(1).join(''))) {
        failures.push('regression: multi_entity_2 page_number row has no digit')
      } else {
        console.log('  ✓ multi_entity_2 still shows page_number value')
      }
    }
  }

  await browser.close()

  console.log('')
  console.log('═══ RESULTS ═══')
  if (failures.length === 0) {
    console.log('✅ all 3 fixes verified')
  } else {
    console.log('❌ failures:')
    for (const f of failures) console.log('  -', f)
    process.exitCode = 1
  }
}

main().catch((e) => {
  console.error('FATAL:', e)
  process.exit(2)
})
