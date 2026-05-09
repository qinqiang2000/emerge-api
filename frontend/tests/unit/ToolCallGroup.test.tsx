import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import ToolCallGroup from '../../src/components/Chat/ToolCallGroup'
import type { ChatEvent } from '../../src/types/chat'

function tc(name: string, opts: Partial<Extract<ChatEvent, { type: 'tool_call' }>> = {}): Extract<ChatEvent, { type: 'tool_call' }> {
  return {
    type: 'tool_call',
    tool_use_id: `tu_${name}`,
    tool_name: name,
    tool_input: {},
    tool_result: 'ok',
    ok: true,
    ...opts,
  }
}

describe('ToolCallGroup', () => {
  it('renders all pills', () => {
    render(<ToolCallGroup calls={[
      tc('mcp__emerge_tools__readiness_check'),
      tc('mcp__emerge_tools__freeze_version', { tool_result: JSON.stringify({ version_id: 'v1' }) }),
    ]} />)
    expect(screen.getByText('readiness_check')).toBeInTheDocument()
    expect(screen.getByText('freeze_version')).toBeInTheDocument()
  })

  it('issue_api_key call routes to KeyTrailCard, not ToolCallPill', () => {
    render(<ToolCallGroup calls={[
      tc('mcp__emerge_tools__issue_api_key', {
        tool_result: { redacted: true, key_prefix: 'ek_abc', key_hash_short: '123456', created_at: 't' },
      }),
    ]} />)
    expect(screen.getByText(/key issued/i)).toBeInTheDocument()
  })

  it('start_job call routes to JobProgressCard, not ToolCallPill', () => {
    render(<ToolCallGroup calls={[
      tc('mcp__emerge_tools__start_job', { tool_result: 'j_abc123def456' }),
    ]} />)
    expect(screen.getByText(/j_abc123def456/)).toBeInTheDocument()
  })

  it('mixed: regular pill + KeyTrailCard side by side', () => {
    render(<ToolCallGroup calls={[
      tc('mcp__emerge_tools__readiness_check'),
      tc('mcp__emerge_tools__issue_api_key', {
        tool_result: { redacted: true, key_prefix: 'ek_x', key_hash_short: 'aaaaaa', created_at: 't' },
      }),
    ]} />)
    expect(screen.getByText('readiness_check')).toBeInTheDocument()
    expect(screen.getByText(/key issued/i)).toBeInTheDocument()
  })
})
