import { describe, expect, it } from 'vitest'
import { canonicalToolName, LEGACY_TOOL_NAMES } from './legacyToolName'

describe('canonicalToolName', () => {
  it('strips the chat-surface prefix', () => {
    expect(canonicalToolName('mcp__emerge_tools__extract_one')).toBe('extract_one')
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
