import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import ToolCallPill from '../../src/components/Chat/ToolCallPill'
import type { ChatEvent } from '../../src/types/chat'

function makeEvent(over: Partial<Extract<ChatEvent, { type: 'tool_call' }>> = {}): Extract<ChatEvent, { type: 'tool_call' }> {
  return {
    type: 'tool_call',
    tool_use_id: 'tu_1',
    tool_name: 'mcp__emerge_tools__freeze_version',
    tool_input: { project_id: 'p_test_1234567' },
    tool_result: undefined,
    ok: true,
    ...over,
  }
}

describe('ToolCallPill', () => {
  it('running state: spinner + no hint', () => {
    const { container } = render(<ToolCallPill event={makeEvent()} />)
    expect(screen.getByText('freeze_version')).toBeInTheDocument()
    expect(container.textContent).not.toContain('·')
    expect(container.querySelector('[data-state="running"]')).not.toBeNull()
  })

  it('done state: check + hint from extractor', () => {
    render(<ToolCallPill event={makeEvent({
      tool_result: JSON.stringify({ version_id: 'v3' }),
      ok: true,
    })} />)
    expect(screen.getByText('freeze_version')).toBeInTheDocument()
    expect(screen.getByText(/v3/)).toBeInTheDocument()
  })

  it('error state: red + error_code', () => {
    render(<ToolCallPill event={makeEvent({
      tool_name: 'mcp__emerge_tools__extract_one',
      tool_result: JSON.stringify({ error_code: 'extract_invalid_json', error_message_en: 'malformed' }),
      ok: false,
    })} />)
    expect(screen.getByText('extract_one')).toBeInTheDocument()
    expect(screen.getByText(/extract_invalid_json/)).toBeInTheDocument()
    const root = screen.getByText('extract_one').closest('[data-state]')
    expect(root?.getAttribute('data-state')).toBe('error')
  })

  it('click toggles details with input + result JSON', () => {
    render(<ToolCallPill event={makeEvent({
      tool_result: JSON.stringify({ version_id: 'v3' }),
      ok: true,
    })} />)
    const btn = screen.getByRole('button', { name: /freeze_version/ })
    fireEvent.click(btn)
    expect(screen.getByText(/project_id/)).toBeInTheDocument()
  })

  it('issue_api_key pill never shows full plaintext when result is redacted', () => {
    render(<ToolCallPill event={makeEvent({
      tool_name: 'mcp__emerge_tools__issue_api_key',
      tool_result: JSON.stringify({ redacted: true, key_prefix: 'ek_abcdefgh', key_hash_short: '123456' }),
      ok: true,
    })} />)
    const btn = screen.getByRole('button', { name: /issue_api_key/ })
    fireEvent.click(btn)
    expect(screen.queryByText(/key_plaintext/)).toBeNull()
    expect(screen.getByText('ek_abcdefgh')).toBeInTheDocument()
  })

  it('strips mcp__emerge_tools__ prefix in displayed name', () => {
    render(<ToolCallPill event={makeEvent({ tool_name: 'mcp__emerge_tools__derive_schema' })} />)
    expect(screen.getByText('derive_schema')).toBeInTheDocument()
    expect(screen.queryByText(/mcp__emerge_tools__/)).toBeNull()
  })
})
