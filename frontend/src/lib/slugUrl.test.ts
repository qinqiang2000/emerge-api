import { describe, expect, it } from 'vitest'

import {
  pathForBench,
  pathForBoard,
  pathForChatId,
  pathForSlug,
  readBenchOpenFromSearch,
  readBoardOpenFromSearch,
  readChatIdFromPathname,
  readSlugFromPathname,
} from './slugUrl'

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

// Bench leaderboard route — `/p/<slug>?bench=1`. Mirrors `?eval=<ts>` shape.
// Bench is project-level (no sub-state) so the value is the literal `1`
// rather than a meaningful payload — the presence of the param IS the state.
describe('readBenchOpenFromSearch', () => {
  it('returns true when ?bench=1 is present', () => {
    expect(readBenchOpenFromSearch('?bench=1')).toBe(true)
  })

  it('returns true on a string without the leading "?"', () => {
    expect(readBenchOpenFromSearch('bench=1')).toBe(true)
  })

  it('returns true when bench coexists with other params', () => {
    expect(readBenchOpenFromSearch('?eval=2026-05-25&bench=1')).toBe(true)
    expect(readBenchOpenFromSearch('?bench=1&review=foo.pdf')).toBe(true)
  })

  it('returns false when bench param is absent', () => {
    expect(readBenchOpenFromSearch('')).toBe(false)
    expect(readBenchOpenFromSearch('?eval=2026-05-25')).toBe(false)
  })

  it('returns false when bench param value is empty', () => {
    // `?bench=` with no value is treated as "not open" — matches the
    // readEvalTsFromSearch convention.
    expect(readBenchOpenFromSearch('?bench=')).toBe(false)
  })
})

describe('pathForBench', () => {
  it('builds /p/{slug}?bench=1', () => {
    expect(pathForBench('us-invoice')).toBe('/p/us-invoice?bench=1')
  })

  it('percent-encodes CJK slugs', () => {
    expect(pathForBench('默沙东_小票')).toBe(
      '/p/%E9%BB%98%E6%B2%99%E4%B8%9C_%E5%B0%8F%E7%A5%A8?bench=1',
    )
  })

  it('round-trips with readBenchOpenFromSearch', () => {
    const url = pathForBench('us-invoice')
    const qs = url.slice(url.indexOf('?'))
    expect(readBenchOpenFromSearch(qs)).toBe(true)
  })
})

// Audit board route — `/p/<slug>?board=1`. Mirrors `?bench=1` exactly.
describe('readBoardOpenFromSearch / pathForBoard', () => {
  it('returns true when ?board=1 is present (with or without "?", alongside others)', () => {
    expect(readBoardOpenFromSearch('?board=1')).toBe(true)
    expect(readBoardOpenFromSearch('board=1')).toBe(true)
    expect(readBoardOpenFromSearch('?eval=2026-05-25&board=1')).toBe(true)
  })

  it('returns false when absent or empty-valued', () => {
    expect(readBoardOpenFromSearch('')).toBe(false)
    expect(readBoardOpenFromSearch('?bench=1')).toBe(false)
    expect(readBoardOpenFromSearch('?board=')).toBe(false)
  })

  it('pathForBoard builds /p/{slug}?board=1, percent-encoding CJK slugs, and round-trips', () => {
    expect(pathForBoard('us-invoice')).toBe('/p/us-invoice?board=1')
    expect(pathForBoard('默沙东_小票')).toBe(
      '/p/%E9%BB%98%E6%B2%99%E4%B8%9C_%E5%B0%8F%E7%A5%A8?board=1',
    )
    const url = pathForBoard('us-invoice')
    expect(readBoardOpenFromSearch(url.slice(url.indexOf('?')))).toBe(true)
  })
})
