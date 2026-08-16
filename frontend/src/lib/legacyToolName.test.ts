import { describe, expect, it } from 'vitest'
import { canonicalToolName, LEGACY_TOOL_NAMES, scoreKindOf } from './legacyToolName'

describe('canonicalToolName', () => {
  it('strips the chat-surface prefix', () => {
    expect(canonicalToolName('mcp__emerge_tools__list_docs')).toBe('list_docs')
  })

  it('strips the headless service prefix', () => {
    expect(canonicalToolName('emerge_ws_list')).toBe('ws_list')
  })

  it('leaves SDK built-ins alone', () => {
    expect(canonicalToolName('Bash')).toBe('Bash')
    expect(canonicalToolName('Read')).toBe('Read')
  })

  it('passes unknown names through unchanged', () => {
    expect(canonicalToolName('mcp__emerge_tools__some_future_tool'))
      .toBe('some_future_tool')
  })

  it('maps every legacy entry to a different, non-empty name', () => {
    for (const [oldName, newName] of Object.entries(LEGACY_TOOL_NAMES)) {
      expect(newName).toBeTruthy()
      expect(newName).not.toBe(oldName)
      expect(canonicalToolName(`mcp__emerge_tools__${oldName}`)).toBe(newName)
    }
  })
})

// P4 Task 7: score(kind=) folds score_audit/score_match. This is the single
// place groupChatEvents.ts (hoist vs. collapse) and MessageList.tsx (which
// card) both read the kind from — pinned here so the two cannot drift, and so
// card selection is asserted directly rather than only via tool registration.
describe('scoreKindOf', () => {
  const CALL = 'mcp__emerge_tools__'

  it('defaults the live `score` name to extract when kind is absent, mirroring the server', () => {
    expect(scoreKindOf(`${CALL}score`, { slug: 'p_x' })).toBe('extract')
  })

  it('reads kind off tool_input for the live `score` name', () => {
    expect(scoreKindOf(`${CALL}score`, { slug: 'p_x', kind: 'audit' })).toBe('audit')
    expect(scoreKindOf(`${CALL}score`, { slug: 'p_x', kind: 'match' })).toBe('match')
    expect(scoreKindOf(`${CALL}score`, { slug: 'p_x', kind: 'extract' })).toBe('extract')
  })

  it('resolves legacy pre-merge transcript names from the NAME, ignoring tool_input', () => {
    // Old recorded calls never carried a `kind` argument at all.
    expect(scoreKindOf(`${CALL}score_audit`, { slug: 'p_x' })).toBe('audit')
    expect(scoreKindOf(`${CALL}score_match`, { slug: 'p_x' })).toBe('match')
  })

  it('returns null for non-score tool calls', () => {
    expect(scoreKindOf(`${CALL}run_audit`, { slug: 'p_x' })).toBeNull()
    expect(scoreKindOf(`${CALL}extract`, { slug: 'p_x' })).toBeNull()
  })

  it('ignores a garbage kind value the same way the server schema enum would reject it', () => {
    // Never reached in practice (the MCP jsonschema `enum` rejects it before
    // a result exists), but the renderer must not crash or silently render a
    // bogus kind as something recognizable if it ever did.
    expect(scoreKindOf(`${CALL}score`, { slug: 'p_x', kind: 'bogus' })).toBe('extract')
  })
})
