import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ExperimentTabStrip from '../../../src/components/ReviewMode/ExperimentTabStrip'
import type { ExperimentSummary } from '../../../src/types/review'

const EXPERIMENTS: ExperimentSummary[] = [
  { experiment_id: 'ex_a', label: 'try Gemma4', prompt_id: 'pr_x', model_id: 'm_y',
    status: 'draft', created_at: '2026-05-13', score: null },
  { experiment_id: 'ex_b', label: 'try notes', prompt_id: 'pr_z', model_id: 'm_y',
    status: 'ran', created_at: '2026-05-13', score: 0.91 },
  { experiment_id: 'ex_c', label: 'archived one', prompt_id: 'pr', model_id: 'm',
    status: 'archived', created_at: '2026-05-13', score: null },
]

describe('ExperimentTabStrip', () => {
  it('renders ⭐ Active + every non-archived experiment by default', () => {
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        modelLabels={{ m_y: 'Gemma 4' }}
      />
    )
    expect(screen.getByText(/Active/i)).toBeInTheDocument()
    // both non-archived experiments are visible without any attach action
    const tabs = screen.getAllByRole('tab')
    const labels = tabs.map((t) => t.textContent)
    expect(labels.some((l) => l?.includes('try Gemma4'))).toBe(true)
    expect(labels.some((l) => l?.includes('try notes'))).toBe(true)
    // archived one is hidden
    expect(labels.some((l) => l?.includes('archived one'))).toBe(false)
  })

  it('clicking an experiment tab calls onSwitch with experiment_id', () => {
    const onSwitch = vi.fn()
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        availableExperiments={EXPERIMENTS}
        onSwitch={onSwitch}
        modelLabels={{}}
      />
    )
    fireEvent.click(screen.getByText('try Gemma4'))
    expect(onSwitch).toHaveBeenCalledWith('ex_a')
  })

  it('clicking ⭐ Active calls onSwitch with "active"', () => {
    const onSwitch = vi.fn()
    render(
      <ExperimentTabStrip
        activeTabKey="ex_a"
        availableExperiments={EXPERIMENTS}
        onSwitch={onSwitch}
        modelLabels={{}}
      />
    )
    fireEvent.click(screen.getByText(/Active/i))
    expect(onSwitch).toHaveBeenCalledWith('active')
  })

  it('selected tab gets aria-selected=true', () => {
    render(
      <ExperimentTabStrip
        activeTabKey="ex_a"
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        modelLabels={{}}
      />
    )
    const tabs = screen.getAllByRole('tab')
    const selected = tabs.find((t) => t.getAttribute('aria-selected') === 'true')
    expect(selected?.textContent).toContain('try Gemma4')
  })

  it('does NOT render an "add tab" button (no popover entry point)', () => {
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        modelLabels={{}}
      />
    )
    expect(screen.queryByRole('button', { name: '+' })).not.toBeInTheDocument()
  })
})
