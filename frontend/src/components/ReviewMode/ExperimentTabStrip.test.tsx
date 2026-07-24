// The tab strip's top line is the model's human name. It resolves it from the
// models store, which can legitimately be stale (a model registered mid-session
// by the agent) — so the fallback chain must never bottom out at the raw
// `m_xxxxxxxx` id while the experiment row itself still carries the name.
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import ExperimentTabStrip, { modelFromExperimentLabel } from './ExperimentTabStrip'
import type { ExperimentSummary } from '../../types/review'

const EXP: ExperimentSummary = {
  experiment_id: 'ex_4biw85y0p7wn',
  label: 'Baseline v9 × qwen3.7-plus',
  prompt_id: 'pr_baseline',
  prompt_version: 9,
  model_id: 'm_1an71pyma3ie',
  status: 'draft',
  created_at: '2026-07-24T08:28:01Z',
  score: null,
}

describe('modelFromExperimentLabel', () => {
  it('reads the model suffix minted by tools/experiment.py', () => {
    expect(modelFromExperimentLabel('Baseline v9 × qwen3.7-plus')).toBe('qwen3.7-plus')
  })

  it('returns null when the label carries no model half', () => {
    expect(modelFromExperimentLabel('Baseline v9')).toBeNull()
    expect(modelFromExperimentLabel('Baseline v9 × ')).toBeNull()
  })

  it('keeps the first separator as the split point (prompt names win)', () => {
    // The prompt half is `split(' × ')[0]`; the model half must be everything
    // after that same first separator so the two halves stay complementary.
    expect(modelFromExperimentLabel('a × b × c')).toBe('b × c')
  })
})

describe('ExperimentTabStrip model name', () => {
  function renderStrip(modelLabels: Record<string, string>) {
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        availableExperiments={[EXP]}
        onSwitch={vi.fn()}
        modelLabels={modelLabels}
      />,
    )
  }

  it('prefers the models store when it knows the id', () => {
    renderStrip({ m_1an71pyma3ie: 'qwen3.7-plus' })
    expect(screen.getByText('qwen3.7-plus')).toBeInTheDocument()
    expect(screen.queryByText('m_1an71pyma3ie')).not.toBeInTheDocument()
  })

  it('falls back to the experiment label when the store is stale', () => {
    renderStrip({})
    expect(screen.getByText('qwen3.7-plus')).toBeInTheDocument()
    expect(screen.queryByText('m_1an71pyma3ie')).not.toBeInTheDocument()
  })

  it('shows the raw id only when nothing else names the model', () => {
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        availableExperiments={[{ ...EXP, label: 'Baseline v9' }]}
        onSwitch={vi.fn()}
        modelLabels={{}}
      />,
    )
    expect(screen.getByText('m_1an71pyma3ie')).toBeInTheDocument()
  })
})
