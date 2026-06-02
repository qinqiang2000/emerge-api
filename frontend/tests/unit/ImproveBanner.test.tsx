import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import ImproveBanner from '../../src/components/Improve/ImproveBanner'
import type { JobSlice } from '../../src/stores/jobs'

const baseJob: JobSlice = {
  jobId: 'j_001',
  projectId: 'p_x',
  status: 'running',
  turns: [
    { type: 'turn', turn: 0, macro_f1: 0.5, per_field: [], saved: true },
    { type: 'turn', turn: 1, macro_f1: 0.6, per_field: [], saved: true },
  ],
  bestTurn: { type: 'turn', turn: 1, macro_f1: 0.6, per_field: [], saved: true },
  targetFields: null,
  endedReason: null,
  err: null,
  _abort: null,
  accepting: false,
  accepted: null,
}

describe('ImproveBanner', () => {
  it('renders live dot', () => {
    render(<ImproveBanner job={baseJob} onOpen={vi.fn()} />)
    const bar = document.querySelector('.improvebar')
    expect(bar).toBeTruthy()
    const dot = bar?.querySelector('.live')
    expect(dot).toBeTruthy()
  })

  it('shows /improve label and turn count', () => {
    render(<ImproveBanner job={baseJob} onOpen={vi.fn()} />)
    expect(screen.getByText('/improve')).toBeInTheDocument()
    expect(screen.getByText(/round 2/)).toBeInTheDocument()
  })

  it('renders open button and calls onOpen when clicked', () => {
    const onOpen = vi.fn()
    render(<ImproveBanner job={baseJob} onOpen={onOpen} />)
    const btn = screen.getByRole('button', { name: /open/i })
    expect(btn).toBeInTheDocument()
    fireEvent.click(btn)
    expect(onOpen).toHaveBeenCalledOnce()
  })

  it('shows 0% progress with no turns', () => {
    const job: JobSlice = { ...baseJob, turns: [] }
    render(<ImproveBanner job={job} onOpen={vi.fn()} />)
    expect(screen.getByText('0%')).toBeInTheDocument()
  })

  it('caps progress at 100% when turns exceed placeholder max', () => {
    const job: JobSlice = {
      ...baseJob,
      turns: Array.from({ length: 15 }, (_, i) => ({
        type: 'turn' as const,
        turn: i,
        macro_f1: 0.5,
        per_field: [],
        saved: true,
      })),
    }
    render(<ImproveBanner job={job} onOpen={vi.fn()} />)
    expect(screen.getByText('100%')).toBeInTheDocument()
  })
})
