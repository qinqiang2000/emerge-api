import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import MessageList from '../../src/components/Chat/MessageList'
import type { ChatEvent } from '../../src/types/chat'

// Integration test: drives MessageList from a ChatEvent[] through the full
// pipeline (groupChatEvents → MessageList → ToolStack / HoistedToolCard → DOM).
// Covers the 2026-05-11 sync-design change: plumbing tools collapse into a
// ToolStack; rich-card tools (score, readiness_check, issue_api_key, start_job)
// hoist out to render as independent blocks. Only `score` is exercised here —
// the other 3 hoisted tools depend on zustand stores (apiKey / projects / jobs)
// and have their own dedicated test files (PublishStage.test, JobProgressCard.test).

function tc(name: string, result: unknown = 'ok'): Extract<ChatEvent, { type: 'tool_call' }> {
  return {
    type: 'tool_call',
    tool_use_id: `tu_${name}`,
    tool_name: name,
    tool_input: {},
    tool_result: result,
    ok: true,
  }
}

describe('MessageList integration: ToolStack + hoisted cards', () => {
  it('plumbing-only: collapses into ToolStack; names hidden until expanded', () => {
    const events: ChatEvent[] = [
      { type: 'agent_text', text: 'starting' },
      tc('mcp__emerge_tools__read_documents'),
      tc('mcp__emerge_tools__derive_schema'),
      tc('mcp__emerge_tools__write_schema'),
    ]
    render(<MessageList events={events} />)

    // Collapsed head visible, italic count + tool noun.
    const head = screen.getByRole('button', { name: /Ran 3 tools/ })
    expect(head).toBeInTheDocument()

    // Plumbing tool names are NOT visible while collapsed (max-height:0).
    // We can't assert visibility via CSS in jsdom, but the ToolStack root
    // should NOT have the 'open' class.
    const stack = screen.getByTestId('tool-stack')
    expect(stack.className).not.toContain('open')

    // Click expands.
    fireEvent.click(head)
    expect(stack.className).toContain('open')

    // Tool names now reachable in the expanded tree.
    expect(screen.getByText('read_documents')).toBeInTheDocument()
    expect(screen.getByText('derive_schema')).toBeInTheDocument()
    expect(screen.getByText('write_schema')).toBeInTheDocument()
  })

  it('singular: 1 plumbing call renders as "Ran 1 tool ›"', () => {
    const events: ChatEvent[] = [tc('mcp__emerge_tools__write_schema')]
    render(<MessageList events={events} />)
    expect(screen.getByRole('button', { name: /Ran 1 tool\b/ })).toBeInTheDocument()
  })

  it('score hoists out: EvalCard renders alongside split ToolStacks', () => {
    // M12.x — accuracy-shaped score result.
    const scoreResult = JSON.stringify({
      field_accuracy_macro: 0.847,
      doc_accuracy: 0.8,
      scored_at: 'just now',
      per_field: [
        { field: 'invoice_number', accuracy: 0.91, correct: 11, total: 12, n_absent_both: 0, not_applicable: false },
        { field: 'vendor_name', accuracy: 0.78, correct: 9, total: 12, n_absent_both: 0, not_applicable: false },
      ],
    })
    const events: ChatEvent[] = [
      tc('mcp__emerge_tools__read_documents'),
      tc('mcp__emerge_tools__derive_schema'),
      tc('mcp__emerge_tools__score', scoreResult),
      tc('mcp__emerge_tools__write_schema'),
    ]
    render(<MessageList events={events} />)

    // Two ToolStack blocks (plumbing before score, plumbing after).
    const stacks = screen.getAllByTestId('tool-stack')
    expect(stacks).toHaveLength(2)
    expect(screen.getByRole('button', { name: /Ran 2 tools/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Ran 1 tool\b/ })).toBeInTheDocument()

    // EvalCard rendered between them — immediately visible, not folded into either ToolStack.
    const evalCard = screen.getByTestId('eval-card')
    expect(evalCard).toBeInTheDocument()
    expect(screen.getByText('eval result')).toBeInTheDocument()
    expect(screen.getByText(/84\.7%/)).toBeInTheDocument()
    expect(screen.getByText('invoice_number')).toBeInTheDocument()
    expect(screen.getByText('vendor_name')).toBeInTheDocument()
  })

  it('all-hoisted run: no empty ToolStack blocks emitted', () => {
    const scoreResult = JSON.stringify({
      field_accuracy_macro: 0.9,
      per_field: [{ field: 'invoice_number', accuracy: 0.9, correct: 9, total: 10, n_absent_both: 0, not_applicable: false }],
    })
    const events: ChatEvent[] = [
      tc('mcp__emerge_tools__score', scoreResult),
    ]
    render(<MessageList events={events} />)
    expect(screen.queryByTestId('tool-stack')).toBeNull()
    expect(screen.getByTestId('eval-card')).toBeInTheDocument()
  })
})
