import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import ProposalCandidateCard from '../../src/components/Improve/ProposalCandidateCard'
import { useJob } from '../../src/stores/jobs'
import type { JobSlice } from '../../src/stores/jobs'
import type { ChatEvent } from '../../src/types/chat'

type ToolCallEvent = Extract<ChatEvent, { type: 'tool_call' }>

const candidateResult = {
  field: 'vendor_name',
  old_description: 'The vendor.',
  new_description: 'The name of the vendor on the invoice.',
}

const candidateEvent: ToolCallEvent = {
  type: 'tool_call',
  tool_name: 'mcp__emerge_tools__propose_description',
  tool_input: { field: 'vendor_name' },
  tool_result: candidateResult,
  ok: true,
}

const baseSlice: JobSlice = {
  jobId: 'j_abc',
  projectId: 'p_x',
  status: 'running',
  turns: [
    { type: 'turn', turn: 0, macro_f1: 0.5, per_field: [], saved: true },
    { type: 'turn', turn: 1, macro_f1: 0.7, per_field: [], saved: true },
  ],
  bestTurn: { type: 'turn', turn: 1, macro_f1: 0.7, per_field: [], saved: true },
  endedReason: null,
  err: null,
  _abort: null,
}

beforeEach(() => {
  useJob.setState({
    byId: {},
    subscribe: vi.fn().mockResolvedValue(undefined) as any,
    pause: vi.fn() as any,
    resume: vi.fn() as any,
    cancel: vi.fn() as any,
    accept: vi.fn().mockResolvedValue(undefined) as any,
  })
})

describe('ProposalCandidateCard', () => {
  it('renders ProposalDiff with field and descriptions', () => {
    render(<ProposalCandidateCard event={candidateEvent} />)
    expect(screen.getByText('vendor_name')).toBeInTheDocument()
    expect(screen.getByText('The vendor.')).toBeInTheDocument()
    expect(screen.getByText('The name of the vendor on the invoice.')).toBeInTheDocument()
  })

  it('accept button is disabled when no running job', () => {
    render(<ProposalCandidateCard event={candidateEvent} />)
    const acceptBtn = screen.getByRole('button', { name: /accept/i })
    expect(acceptBtn).toBeDisabled()
  })

  it('accept button is enabled when running job with bestTurn exists', () => {
    useJob.setState({ byId: { j_abc: baseSlice } })
    render(<ProposalCandidateCard event={candidateEvent} />)
    const acceptBtn = screen.getByRole('button', { name: /^accept$/i })
    expect(acceptBtn).not.toBeDisabled()
  })

  it('accept button is disabled when running job has no bestTurn yet', () => {
    useJob.setState({ byId: { j_abc: { ...baseSlice, bestTurn: null } } })
    render(<ProposalCandidateCard event={candidateEvent} />)
    const acceptBtn = screen.getByRole('button', { name: /^accept$/i })
    expect(acceptBtn).toBeDisabled()
  })

  it('calls useJob.accept with jobId and bestTurn.turn on click', async () => {
    const mockAccept = vi.fn().mockResolvedValue(undefined)
    useJob.setState({ byId: { j_abc: baseSlice }, accept: mockAccept as any })

    render(<ProposalCandidateCard event={candidateEvent} />)
    const acceptBtn = screen.getByRole('button', { name: /^accept$/i })
    fireEvent.click(acceptBtn)

    // Wait for async accept
    await vi.waitFor(() => {
      expect(mockAccept).toHaveBeenCalledWith('j_abc', 1)
    })
  })

  it('shows accepted checkmark after accept', async () => {
    const mockAccept = vi.fn().mockResolvedValue(undefined)
    useJob.setState({ byId: { j_abc: baseSlice }, accept: mockAccept as any })

    render(<ProposalCandidateCard event={candidateEvent} />)
    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }))

    await vi.waitFor(() => {
      expect(screen.getByText(/accepted ✓/)).toBeInTheDocument()
    })
  })

  it('dismiss button removes the card', () => {
    render(<ProposalCandidateCard event={candidateEvent} />)
    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }))
    expect(screen.queryByText('vendor_name')).not.toBeInTheDocument()
  })
})
