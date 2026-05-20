import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

import JobProgressCard, { formatJobLine } from '../../src/components/Chat/JobProgressCard'
import { useJob } from '../../src/stores/jobs'
import type { JobSlice } from '../../src/stores/jobs'

const baseSlice: JobSlice = {
  jobId: 'j_xyz',
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
    byId: { j_xyz: { ...baseSlice } },
    subscribe: vi.fn().mockResolvedValue(undefined) as any,
    pause: vi.fn() as any,
    resume: vi.fn() as any,
    cancel: vi.fn() as any,
    accept: vi.fn() as any,
  })
})

describe('JobProgressCard', () => {
  it('renders turn and best-f1 line', () => {
    render(<JobProgressCard jobId="j_xyz" />)
    expect(screen.getByText(/turn 1/i)).toBeInTheDocument()
    expect(screen.getByText(/0\.70/)).toBeInTheDocument()
  })

  it('shows pause button when running, hides resume', () => {
    render(<JobProgressCard jobId="j_xyz" />)
    expect(screen.getByRole('button', { name: /pause/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /resume/i })).not.toBeInTheDocument()
  })

  it('shows accept-candidate button after ended=done with bestTurn > 0', () => {
    useJob.setState({
      byId: { j_xyz: { ...baseSlice, status: 'done', endedReason: 'max_turn' } },
    })
    render(<JobProgressCard jobId="j_xyz" />)
    expect(screen.getByRole('button', { name: /accept candidate/i })).toBeInTheDocument()
  })

  it('hides accept button and shows baseline-best hint when bestTurn === 0', () => {
    useJob.setState({
      byId: { j_xyz: {
        ...baseSlice,
        status: 'done',
        endedReason: 'max_turn',
        bestTurn: { type: 'turn', turn: 0, macro_f1: 0.96, per_field: [], saved: true },
      } },
    })
    render(<JobProgressCard jobId="j_xyz" />)
    expect(screen.queryByRole('button', { name: /accept candidate/i })).not.toBeInTheDocument()
    expect(screen.getByText(/baseline still best/i)).toBeInTheDocument()
  })

  it('shows accept button after cancelled with bestTurn > 0 above baseline', () => {
    useJob.setState({
      byId: { j_xyz: { ...baseSlice, status: 'cancelled', endedReason: 'cancelled' } },
    })
    render(<JobProgressCard jobId="j_xyz" />)
    expect(screen.getByRole('button', { name: /accept candidate/i })).toBeInTheDocument()
  })

  it('shows baseline-best hint after cancelled when best equals baseline', () => {
    useJob.setState({
      byId: { j_xyz: {
        ...baseSlice,
        status: 'cancelled',
        endedReason: 'cancelled',
        bestTurn: { type: 'turn', turn: 0, macro_f1: 0.5, per_field: [], saved: true },
      } },
    })
    render(<JobProgressCard jobId="j_xyz" />)
    expect(screen.queryByRole('button', { name: /accept candidate/i })).not.toBeInTheDocument()
    expect(screen.getByText(/baseline still best/i)).toBeInTheDocument()
  })
})

describe('formatJobLine', () => {
  it('shows baseline and delta when a later turn improved (accuracy field preferred)', () => {
    const line = formatJobLine({
      turns: [
        { turn: 0, field_accuracy_macro: 0.71, macro_f1: 0.71, saved: true },
        { turn: 4, field_accuracy_macro: 0.83, macro_f1: 0.83, saved: true },
      ],
      bestTurn: { turn: 4, field_accuracy_macro: 0.83, macro_f1: 0.83, saved: true },
    } as any)
    expect(line).toContain('best acc 0.83')
    expect(line).toContain('turn 4')
    expect(line).toContain('baseline 0.71')
    expect(line).toMatch(/\+0\.12|Δ\s*\+0\.12/)
  })
  it('reads "baseline still best" when turn 0 is best', () => {
    const line = formatJobLine({
      turns: [{ turn: 0, field_accuracy_macro: 0.91, macro_f1: 0.91, saved: true }],
      bestTurn: { turn: 0, field_accuracy_macro: 0.91, macro_f1: 0.91, saved: true },
    } as any)
    expect(line).toContain('best acc 0.91')
  })
  it('falls back to legacy macro_f1 when field_accuracy_macro missing', () => {
    // Replays a pre-M12.x job JSONL — only `macro_f1` present.
    const line = formatJobLine({
      turns: [{ turn: 0, macro_f1: 0.6, saved: true }],
      bestTurn: { turn: 0, macro_f1: 0.6, saved: true },
    } as any)
    expect(line).toContain('best acc 0.60')
  })
})
