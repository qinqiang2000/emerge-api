import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

import ToolCallGroup from '../../src/components/Chat/ToolCallGroup'
import { useJob } from '../../src/stores/jobs'
import type { ChatEvent } from '../../src/types/chat'
import type { JobSlice } from '../../src/stores/jobs'

beforeEach(() => {
  useJob.setState({
    byId: {},
    subscribe: vi.fn().mockResolvedValue(undefined) as any,
    pause: vi.fn() as any,
    resume: vi.fn() as any,
    cancel: vi.fn() as any,
    accept: vi.fn() as any,
  })
})

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
    const slice: JobSlice = {
      jobId: 'j_abc123def456',
      projectId: 'p_x',
      status: 'running',
      turns: [],
      bestTurn: null,
      endedReason: null,
      err: null,
      _abort: null,
    }
    useJob.setState({ byId: { j_abc123def456: slice } })
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
