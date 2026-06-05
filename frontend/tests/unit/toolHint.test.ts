import { describe, expect, it } from 'vitest'

import { toolShortHint } from '../../src/lib/toolHint'

describe('toolShortHint', () => {
  it('returns null for unknown tool name', () => {
    expect(toolShortHint('mcp__emerge_tools__no_such_thing', 'whatever')).toBeNull()
  })

  it('derive_schema: returns "{N} fields" from a list-shaped result', () => {
    expect(toolShortHint('mcp__emerge_tools__derive_schema',
      "[{'name':'a','type':'string','description':'x'},{'name':'b','type':'number','description':'y'}]"
    )).toBe('2 fields')
  })

  it('read_schema: same shape, returns "{N} fields"', () => {
    expect(toolShortHint('mcp__emerge_tools__read_schema',
      "[{'name':'a','type':'string','description':'x'}]"
    )).toBe('1 field')
  })

  it('score: returns "macro_f1=0.97"', () => {
    const result = JSON.stringify({ macro_f1: 0.9712, per_field: [] })
    expect(toolShortHint('mcp__emerge_tools__score', result)).toBe('macro_f1=0.97')
  })

  it('freeze_version: returns the version_id', () => {
    const result = JSON.stringify({ version_id: 'v3' })
    expect(toolShortHint('mcp__emerge_tools__freeze_version', result)).toBe('v3')
  })

  it('issue_api_key: redacted result returns prefix only', () => {
    const result = JSON.stringify({
      redacted: true, key_prefix: 'ek_abcdefgh', key_hash_short: '123456',
    })
    expect(toolShortHint('mcp__emerge_tools__issue_api_key', result)).toBe('ek_abcdefgh')
  })

  it('readiness_check: returns "{pass}/{total} pass"', () => {
    const result = JSON.stringify({
      checks: [
        { key: 'a', status: 'pass', detail: '' },
        { key: 'b', status: 'pass', detail: '' },
        { key: 'c', status: 'fail', detail: '' },
      ],
      hard_pass: false,
    })
    expect(toolShortHint('mcp__emerge_tools__readiness_check', result)).toBe('2/3 pass')
  })

  it('contract_diff: returns "+{added} -{removed}"', () => {
    const result = JSON.stringify({ added: ['x'], removed: ['y', 'z'], type_changed: [], enum_narrowed: [], is_breaking: true })
    expect(toolShortHint('mcp__emerge_tools__contract_diff', result)).toBe('+1 -2 (breaking)')
  })

  it('start_job: returns "job {short}"', () => {
    expect(toolShortHint('mcp__emerge_tools__start_job', 'j_abc123def456')).toBe('job j_abc123de')
  })

  it('list_docs / list_reviewed / list_projects: returns "{N} items"', () => {
    expect(toolShortHint('mcp__emerge_tools__list_docs', "[{'a':1},{'b':2},{'c':3}]")).toBe('3 docs')
    expect(toolShortHint('mcp__emerge_tools__list_reviewed', "[{'a':1}]")).toBe('1 reviewed')
    expect(toolShortHint('mcp__emerge_tools__list_projects', "[]")).toBe('0 projects')
  })

  it('returns null for non-string non-object input that does not parse', () => {
    expect(toolShortHint('mcp__emerge_tools__score', null)).toBeNull()
    expect(toolShortHint('mcp__emerge_tools__score', undefined)).toBeNull()
  })

  it('does NOT throw on malformed JSON', () => {
    expect(() => toolShortHint('mcp__emerge_tools__score', '{not json')).not.toThrow()
    expect(toolShortHint('mcp__emerge_tools__score', '{not json')).toBeNull()
  })

  it('matches both raw and mcp__emerge_tools__-prefixed names', () => {
    expect(toolShortHint('freeze_version', JSON.stringify({ version_id: 'v9' }))).toBe('v9')
    expect(toolShortHint('mcp__emerge_tools__freeze_version', JSON.stringify({ version_id: 'v9' }))).toBe('v9')
  })
})
