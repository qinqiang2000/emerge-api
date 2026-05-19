import { describe, expect, it } from 'vitest'

import { pathForChatId, pathForSlug, readChatIdFromPathname, readSlugFromPathname } from './slugUrl'

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

describe('readChatIdFromPathname', () => {
  it('parses the chat id out of /c/{chat_id}', () => {
    expect(readChatIdFromPathname('/c/c_abcdef123456')).toBe('c_abcdef123456')
  })

  it('ignores the search string', () => {
    expect(readChatIdFromPathname('/c/c_abcdef123456?from=hero')).toBe('c_abcdef123456')
  })

  it('returns null on /p/ paths and root', () => {
    expect(readChatIdFromPathname('/')).toBeNull()
    expect(readChatIdFromPathname('/p/us-invoice')).toBeNull()
  })

  it('returns null when /c/ has no id', () => {
    expect(readChatIdFromPathname('/c/')).toBeNull()
  })

  it('returns null on malformed percent-encoding', () => {
    expect(readChatIdFromPathname('/c/%E0')).toBeNull()
  })
})

describe('pathForChatId', () => {
  it('builds /c/{chat_id} for the standard id shape', () => {
    expect(pathForChatId('c_abcdef123456')).toBe('/c/c_abcdef123456')
  })

  it('renders root path when chat id is null', () => {
    expect(pathForChatId(null)).toBe('/')
  })

  it('preserves search and hash', () => {
    expect(pathForChatId('c_abcdef123456', '?tab=docs', '#turn-3')).toBe('/c/c_abcdef123456?tab=docs#turn-3')
  })

  it('round-trips with readChatIdFromPathname', () => {
    const ids = ['c_abcdef123456', 'c_0000aabbccdd']
    for (const id of ids) {
      expect(readChatIdFromPathname(pathForChatId(id))).toBe(id)
    }
  })
})
