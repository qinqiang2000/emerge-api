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
  it('renders one card per non-archived experiment (no implicit Active tab)', () => {
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        modelLabels={{ m_y: 'Gemma 4' }}
      />
    )
    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(2)
    // archived experiment is excluded
    expect(screen.queryByText(/archived one/)).not.toBeInTheDocument()
    // each card shows model on top, prompt label on bottom
    expect(screen.getAllByText('Gemma 4').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('try Gemma4')).toBeInTheDocument()
    expect(screen.getByText('try notes')).toBeInTheDocument()
  })

  it('no "⭐ Active" chip — canonical view is implicit', () => {
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        modelLabels={{}}
      />
    )
    expect(screen.queryByRole('tab', { name: /Active/i })).not.toBeInTheDocument()
  })

  it('clicking an unselected card calls onSwitch with the experiment_id', () => {
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

  it('clicking the already-selected card toggles back to canonical (active)', () => {
    const onSwitch = vi.fn()
    render(
      <ExperimentTabStrip
        activeTabKey="ex_a"
        availableExperiments={EXPERIMENTS}
        onSwitch={onSwitch}
        modelLabels={{}}
      />
    )
    fireEvent.click(screen.getByText('try Gemma4'))
    expect(onSwitch).toHaveBeenCalledWith('active')
  })

  it('selected tab gets aria-selected=true and includes its prompt label', () => {
    render(
      <ExperimentTabStrip
        activeTabKey="ex_a"
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        modelLabels={{}}
      />
    )
    const selected = screen.getAllByRole('tab').find((t) => t.getAttribute('aria-selected') === 'true')
    expect(selected?.textContent).toContain('try Gemma4')
  })

  it('does NOT render an "add tab" button', () => {
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
