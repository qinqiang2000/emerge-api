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
  it('renders the ⭐ Active tab + each attached experiment tab', () => {
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        attachedExperimentIds={['ex_a', 'ex_b']}
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        onAttach={() => {}}
        onDetach={() => {}}
        modelLabels={{ m_y: 'Gemma 4' }}
      />
    )
    expect(screen.getByText(/Active/i)).toBeInTheDocument()
    expect(screen.getByText('try Gemma4')).toBeInTheDocument()
    expect(screen.getByText('try notes')).toBeInTheDocument()
  })

  it('clicking an experiment tab calls onSwitch with experiment_id', () => {
    const onSwitch = vi.fn()
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        attachedExperimentIds={['ex_a']}
        availableExperiments={EXPERIMENTS}
        onSwitch={onSwitch}
        onAttach={() => {}}
        onDetach={() => {}}
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
        attachedExperimentIds={['ex_a']}
        availableExperiments={EXPERIMENTS}
        onSwitch={onSwitch}
        onAttach={() => {}}
        onDetach={() => {}}
        modelLabels={{}}
      />
    )
    fireEvent.click(screen.getByText(/Active/i))
    expect(onSwitch).toHaveBeenCalledWith('active')
  })

  it('[+] popover lists unattached non-archived experiments', () => {
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        attachedExperimentIds={['ex_a']}
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        onAttach={() => {}}
        onDetach={() => {}}
        modelLabels={{}}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: '+' }))
    // ex_a is already attached → only ex_b (non-archived) shown; ex_c (archived) excluded
    const menu = screen.getByRole('menu')
    expect(menu).toHaveTextContent('try notes')
    expect(menu).not.toHaveTextContent('archived one')
    expect(menu).not.toHaveTextContent('try Gemma4')
  })

  it('clicking a popover item calls onAttach and closes the popover', () => {
    const onAttach = vi.fn()
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        attachedExperimentIds={[]}
        availableExperiments={EXPERIMENTS.slice(0, 1)}
        onSwitch={() => {}}
        onAttach={onAttach}
        onDetach={() => {}}
        modelLabels={{}}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: '+' }))
    fireEvent.click(screen.getByRole('menuitem', { name: /try Gemma4/i }))
    expect(onAttach).toHaveBeenCalledWith('ex_a')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('[+] popover shows empty state when no candidates remain', () => {
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        attachedExperimentIds={['ex_a', 'ex_b']}
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        onAttach={() => {}}
        onDetach={() => {}}
        modelLabels={{}}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: '+' }))
    expect(screen.getByText(/no more experiments to attach/i)).toBeInTheDocument()
  })

  it('right-click on an experiment tab triggers detach', () => {
    const onDetach = vi.fn()
    render(
      <ExperimentTabStrip
        activeTabKey="ex_a"
        attachedExperimentIds={['ex_a']}
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        onAttach={() => {}}
        onDetach={onDetach}
        modelLabels={{}}
      />
    )
    fireEvent.contextMenu(screen.getByText('try Gemma4'))
    expect(onDetach).toHaveBeenCalledWith('ex_a')
  })

  it('right-click on the ⭐ Active tab does NOT trigger detach', () => {
    const onDetach = vi.fn()
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        attachedExperimentIds={[]}
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        onAttach={() => {}}
        onDetach={onDetach}
        modelLabels={{}}
      />
    )
    fireEvent.contextMenu(screen.getByText(/Active/i))
    expect(onDetach).not.toHaveBeenCalled()
  })

  it('selected tab gets aria-selected=true', () => {
    render(
      <ExperimentTabStrip
        activeTabKey="ex_a"
        attachedExperimentIds={['ex_a']}
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        onAttach={() => {}}
        onDetach={() => {}}
        modelLabels={{}}
      />
    )
    const tabs = screen.getAllByRole('tab')
    const selected = tabs.find((t) => t.getAttribute('aria-selected') === 'true')
    expect(selected?.textContent).toContain('try Gemma4')
  })
})
