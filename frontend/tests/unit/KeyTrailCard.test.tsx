import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import KeyTrailCard from '../../src/components/Publish/KeyTrailCard'


describe('KeyTrailCard', () => {
  it('renders prefix and short hash from a redacted tool result', () => {
    render(<KeyTrailCard event={{
      type: 'tool_call',
      tool_use_id: 'tu_1',
      tool_name: 'mcp__emerge_tools__issue_api_key',
      tool_input: { project_id: 'p_abc' },
      tool_result: {
        redacted: true,
        key_prefix: 'ek_abcdefgh',
        key_hash_short: 'abcdef',
        created_at: '2026-05-09T01:23:45Z',
      },
      ok: true,
    }} />)
    expect(screen.getByText(/ek_abcdefgh/)).toBeInTheDocument()
    expect(screen.getByText(/hash abcdef/)).toBeInTheDocument()
    expect(screen.getByText(/key issued/i)).toBeInTheDocument()
  })

  it('does not render plaintext defensively', () => {
    render(<KeyTrailCard event={{
      type: 'tool_call',
      tool_use_id: 'tu_1',
      tool_name: 'mcp__emerge_tools__issue_api_key',
      tool_input: { project_id: 'p_abc' },
      tool_result: {
        redacted: true,
        key_prefix: 'ek_xxx',
        key_hash_short: '123abc',
        created_at: 't',
      },
      ok: true,
    }} />)
    expect(screen.queryByText(/ek_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx/)).toBeNull()
  })
})
