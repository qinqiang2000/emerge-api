// Lightweight i18n: zustand store + dict lookup + {var} interpolation.
//
// Adding a new language:
//   1. Drop `src/i18n/<code>.ts` exporting a `Dict` with the same keys as en.ts
//   2. Register it in DICTIONARIES below and extend the `Locale` type
//   3. Add the option to LANG_OPTIONS in UserMenu
// No other code touches.
import { create } from 'zustand'

import en from './en'
import zh from './zh'
import type { Dict, Locale } from './types'
import { SUPPORTED_LOCALES } from './types'

export type { Locale } from './types'
export { SUPPORTED_LOCALES } from './types'

const DICTIONARIES: Record<Locale, Dict> = { en, zh }
const STORAGE_KEY = 'emerge.ui.lang'

function isLocale(v: unknown): v is Locale {
  return typeof v === 'string' && (SUPPORTED_LOCALES as readonly string[]).includes(v)
}

/** RFC 4647 "lookup" against SUPPORTED_LOCALES: walk the caller's ordered
 *  preference list, matching the full tag first (e.g. `zh-CN`) then its base
 *  subtag (`zh`). Returns null if nothing in the list is supported. */
function negotiateLocale(prefs: readonly string[]): Locale | null {
  for (const tag of prefs) {
    const lower = tag.toLowerCase()
    if (isLocale(lower)) return lower
    const base = lower.split('-')[0]
    if (isLocale(base)) return base
  }
  return null
}

/** Language negotiation chain (best-practice priority order):
 *   1. explicit, persisted user choice (localStorage) — never auto-overridden
 *   2. browser preference list (`navigator.languages`, ordered) → lookup
 *   3. default fallback = product's primary locale 'zh' (China-market product;
 *      this only fires for browsers preferring neither zh nor en)
 *  Only #1 is sticky; a first-time visitor with no stored choice follows their
 *  browser, and switching language later writes #1 so detection stops kicking in. */
function detectLocale(): Locale {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (isLocale(v)) return v
  } catch { /* ignore */ }
  try {
    const prefs = navigator.languages?.length ? navigator.languages : [navigator.language]
    const hit = negotiateLocale(prefs)
    if (hit) return hit
  } catch { /* ignore */ }
  return 'zh'
}

/** Keep <html lang> in step with the active locale (a11y + SEO best practice). */
function applyHtmlLang(locale: Locale): void {
  try { document.documentElement.lang = locale } catch { /* ignore */ }
}

interface I18nState {
  locale: Locale
  setLocale: (l: Locale) => void
}

const initialLocale = detectLocale()
applyHtmlLang(initialLocale)

export const useI18n = create<I18nState>(set => ({
  locale: initialLocale,
  setLocale(l) {
    set({ locale: l })
    applyHtmlLang(l)
    try { localStorage.setItem(STORAGE_KEY, l) } catch { /* ignore */ }
    try { window.dispatchEvent(new CustomEvent('emerge:lang', { detail: l })) } catch { /* ignore */ }
  },
}))

// Cross-source sync: another tab (via `storage`) or direct dispatch from
// legacy callers (UserMenu's old `emerge:lang` event) shouldn't fall out of
// step with the store.
if (typeof window !== 'undefined') {
  window.addEventListener('emerge:lang', (e: Event) => {
    const detail = (e as CustomEvent).detail
    if (isLocale(detail) && useI18n.getState().locale !== detail) {
      useI18n.setState({ locale: detail })
      applyHtmlLang(detail)
    }
  })
  window.addEventListener('storage', (e: StorageEvent) => {
    if (e.key !== STORAGE_KEY) return
    if (isLocale(e.newValue) && useI18n.getState().locale !== e.newValue) {
      useI18n.setState({ locale: e.newValue })
      applyHtmlLang(e.newValue)
    }
  })
}

const VAR_RE = /\{(\w+)\}/g

export function format(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template
  return template.replace(VAR_RE, (_, k: string) => {
    const v = vars[k]
    return v === undefined ? `{${k}}` : String(v)
  })
}

export function translate(locale: Locale, key: string, vars?: Record<string, string | number>): string {
  const dict = DICTIONARIES[locale] ?? DICTIONARIES.en
  const raw = dict[key] ?? DICTIONARIES.en[key] ?? key
  return format(raw, vars)
}

/** Imperative read — for non-React call sites (zustand actions, event handlers
 *  outside the render tree). Reads from the live store on each call so it's
 *  always current. React components should prefer `useT()` to subscribe. */
export function t(key: string, vars?: Record<string, string | number>): string {
  return translate(useI18n.getState().locale, key, vars)
}

/** React hook — subscribes to locale changes so the consuming component
 *  re-renders when the user picks a different language. */
export function useT() {
  const locale = useI18n(s => s.locale)
  return (key: string, vars?: Record<string, string | number>) => translate(locale, key, vars)
}
