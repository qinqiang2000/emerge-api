import { describe, expect, it } from 'vitest'

import { pathForSlug, readSlugFromPathname } from './slugUrl'

describe('readSlugFromPathname', () => {
  it('parses the slug out of /p/{slug}', () => {
    expect(readSlugFromPathname('/p/us-invoice')).toBe('us-invoice')
  })

  it('decodes percent-encoded CJK slugs', () => {
    // `默沙东_小票` encoded.
    expect(readSlugFromPathname('/p/%E9%BB%98%E6%B2%99%E4%B8%9C_%E5%B0%8F%E7%A5%A8')).toBe('默沙东_小票')
  })

  it('ignores the search string', () => {
    expect(readSlugFromPathname('/p/recipe?newChat=1')).toBe('recipe')
  })

  it('returns null for the root path', () => {
    expect(readSlugFromPathname('/')).toBeNull()
  })

  it('returns null when /p/ has no slug', () => {
    expect(readSlugFromPathname('/p/')).toBeNull()
  })

  it('returns null on malformed percent-encoding', () => {
    // Lone `%` triggers URIError inside decodeURIComponent — the helper must
    // swallow that and yield null instead of crashing the App mount effect.
    expect(readSlugFromPathname('/p/%E0')).toBeNull()
  })
})

describe('pathForSlug', () => {
  it('builds /p/{slug} for plain ASCII', () => {
    expect(pathForSlug('us-invoice')).toBe('/p/us-invoice')
  })

  it('percent-encodes CJK slugs', () => {
    expect(pathForSlug('默沙东_小票')).toBe('/p/%E9%BB%98%E6%B2%99%E4%B8%9C_%E5%B0%8F%E7%A5%A8')
  })

  it('renders root path when slug is null', () => {
    expect(pathForSlug(null)).toBe('/')
  })

  it('preserves search and hash', () => {
    expect(pathForSlug('us-invoice', '?tab=docs', '#field-3')).toBe('/p/us-invoice?tab=docs#field-3')
  })

  it('round-trips with readSlugFromPathname', () => {
    const slugs = ['us-invoice', '默沙东_小票', 'q4-2025', 'a b c']
    for (const s of slugs) {
      expect(readSlugFromPathname(pathForSlug(s))).toBe(s)
    }
  })
})
