import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ExperimentTabStrip from '../../../src/components/ReviewMode/ExperimentTabStrip'
import type { ExperimentSummary } from '../../../src/types/review'

const EXPERIMENTS: ExperimentSummary[] = [
  { experiment_id: 'ex_a', label: 'try Gemma4', prompt_id: 'pr_x', model_id: 'm_y',
    prompt_version: 1, status: 'draft', created_at: '2026-05-13', score: null },
  { experiment_id: 'ex_b', label: 'try notes', prompt_id: 'pr_z', model_id: 'm_y',
    prompt_version: 1, status: 'ran', created_at: '2026-05-13', score: 0.91 },
  { experiment_id: 'ex_c', label: 'archived one', prompt_id: 'pr', model_id: 'm',
    prompt_version: 1, status: 'archived', created_at: '2026-05-13', score: null },
]

describe('ExperimentTabStrip', () => {
  it('renders the ✏ annotation tab first, then one card per non-archived experiment', () => {
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        modelLabels={{ m_y: 'Gemma 4' }}
      />
    )
    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(3) // annotation + 2 non-archived
    // first tab is annotation
    expect(tabs[0]).toHaveTextContent(/ground truth/i)
    // archived experiment is excluded
    expect(screen.queryByText(/archived one/)).not.toBeInTheDocument()
    expect(screen.getByText('try Gemma4')).toBeInTheDocument()
    expect(screen.getByText('try notes')).toBeInTheDocument()
  })

  it('annotation tab is rendered with role=tab, aria-selected reflects active state', () => {
    const { rerender } = render(
      <ExperimentTabStrip
        activeTabKey="active"
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        modelLabels={{}}
      />
    )
    const annot = screen.getByRole('tab', { name: /ground truth/i })
    expect(annot.getAttribute('aria-selected')).toBe('true')
    rerender(
      <ExperimentTabStrip
        activeTabKey="ex_a"
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        modelLabels={{}}
      />
    )
    expect(screen.getByRole('tab', { name: /ground truth/i }).getAttribute('aria-selected')).toBe('false')
  })

  it('clicking the annotation tab calls onSwitch with "active"', () => {
    const onSwitch = vi.fn()
    render(
      <ExperimentTabStrip
        activeTabKey="ex_a"
        availableExperiments={EXPERIMENTS}
        onSwitch={onSwitch}
        modelLabels={{}}
      />
    )
    fireEvent.click(screen.getByRole('tab', { name: /ground truth/i }))
    expect(onSwitch).toHaveBeenCalledWith('active')
  })

  it('clicking a prediction card calls onSwitch with its experiment_id (no toggle)', () => {
    const onSwitch = vi.fn()
    render(
      <ExperimentTabStrip
        activeTabKey="ex_a"
        availableExperiments={EXPERIMENTS}
        onSwitch={onSwitch}
        modelLabels={{}}
      />
    )
    // clicking the already-selected card is a no-op switch (same key), not a toggle
    fireEvent.click(screen.getByText('try Gemma4'))
    expect(onSwitch).toHaveBeenCalledWith('ex_a')
  })

  it('selected prediction card has aria-selected=true and contains its prompt label', () => {
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
