import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ReviewOverlay from '../../../src/components/ReviewMode/ReviewOverlay'
import { useExperiments } from '../../../src/stores/experiments'
import { useReview } from '../../../src/stores/review'
import { useSchema } from '../../../src/stores/schema'
import { useDocs } from '../../../src/stores/docs'
import { useModels } from '../../../src/stores/models'

const SCHEMA = [
  { name: 'supplier', type: 'string', description: 'supplier name' },
]

function seedStores(opts: {
  activeTab?: 'active' | string
  predictionsByExp?: Record<string, { entities: Record<string, unknown>[] } | null>
  activeEntities?: Record<string, unknown>[]
}) {
  useSchema.setState({
    byProject: { 'p_x': SCHEMA as never },
  })
  useDocs.setState({
    // doc_id is a stale field carried by the fixture; type was tightened
    // earlier this milestone. Cast through unknown so the test compiles.
    byProject: { 'p_x': [
      { doc_id: 'd_y', filename: 'sample.pdf', ext: 'pdf', page_count: 1,
        uploaded_at: '2026-05-13', has_prediction: true, has_reviewed: false } as unknown as import('../../../src/types/review').DocSummary,
    ] },
  })
  useExperiments.setState({
    list: { 'p_x': [
      { experiment_id: 'ex_a', label: 'gemma', prompt_id: 'pr', model_id: 'm',
        status: 'draft', created_at: '2026-05-13', score: null },
    ] },
    loading: {},
  })
  useModels.setState({
    list: { 'p_x': [
      { model_id: 'm', label: 'Gemma 4', provider: 'google',
        provider_model_id: 'gemma-4-12b-it', is_active: true, created_at: '2026-05-13' },
    ] },
    activeByProject: {},
    loading: {},
  })
  useReview.setState({
    activeProjectId: 'p_x', activeFilename: 'd_y',
    entities: opts.activeEntities ?? [{ supplier: 'ACTIVE' }],
    evidence: null, notes: {},
    activeTabKey: opts.activeTab ?? 'active',
    predictionsByExp: opts.predictionsByExp ?? {},
    loading: false, saving: false, err: null, page: 1, pageCount: 1,
  })
}

describe('ReviewOverlay tab integration', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    }))
  })

  it('renders the ✏ reviewed tab + one card per experiment', () => {
    seedStores({})
    render(<ReviewOverlay onBack={() => {}} />)
    expect(screen.getByRole('tablist')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /reviewed/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /gemma/i })).toBeInTheDocument()
  })

  it('in canonical mode (activeTabKey=active), the field shows active entities and inputs are editable', () => {
    seedStores({
      activeTab: 'active',
      activeEntities: [{ supplier: 'ACTIVE_VAL' }],
    })
    render(<ReviewOverlay onBack={() => {}} />)
    expect(screen.getByText('ACTIVE_VAL')).toBeInTheDocument()
    // value span has contentEditable=true on active tab
    const val = screen.getByText('ACTIVE_VAL').closest('[contenteditable]') as HTMLElement
    expect(val.getAttribute('contenteditable')).toBe('true')
  })

  it('switching to an experiment tab renders experiment extract entities, read-only', () => {
    seedStores({
      activeTab: 'ex_a',
      predictionsByExp: { 'ex_a': { entities: [{ supplier: 'FROM_EXPERIMENT' }] } },
      activeEntities: [{ supplier: 'ACTIVE_VAL' }],
    })
    render(<ReviewOverlay onBack={() => {}} />)
    expect(screen.getByText('FROM_EXPERIMENT')).toBeInTheDocument()
    expect(screen.queryByText('ACTIVE_VAL')).not.toBeInTheDocument()
    const val = screen.getByText('FROM_EXPERIMENT').closest('[contenteditable]') as HTMLElement
    expect(val.getAttribute('contenteditable')).toBe('false')
  })

  it('save button is enabled on active tab, disabled on experiment tab', () => {
    seedStores({ activeTab: 'active' })
    const { rerender } = render(<ReviewOverlay onBack={() => {}} />)
    const saveBtn = screen.getByRole('button', { name: /save/i }) as HTMLButtonElement
    expect(saveBtn.disabled).toBe(false)

    seedStores({
      activeTab: 'ex_a',
      predictionsByExp: { 'ex_a': { entities: [{}] } },
    })
    rerender(<ReviewOverlay onBack={() => {}} />)
    const saveBtn2 = screen.getByRole('button', { name: /save/i }) as HTMLButtonElement
    expect(saveBtn2.disabled).toBe(true)
  })

  it('experiment tab with no cached extract shows the field area gracefully', () => {
    seedStores({
      activeTab: 'ex_a',
      predictionsByExp: { 'ex_a': null },
    })
    render(<ReviewOverlay onBack={() => {}} />)
    // The overlay should render without crashing; the tab strip is present
    expect(screen.getByRole('tablist')).toBeInTheDocument()
  })

  it('shows the "adopt as annotation" button only on prediction tabs', () => {
    seedStores({ activeTab: 'active' })
    const { rerender } = render(<ReviewOverlay onBack={() => {}} />)
    expect(screen.queryByRole('button', { name: /adopt this prediction/i })).not.toBeInTheDocument()

    seedStores({
      activeTab: 'ex_a',
      predictionsByExp: { 'ex_a': { entities: [{ supplier: 'EX' }] } },
    })
    rerender(<ReviewOverlay onBack={() => {}} />)
    expect(screen.getByRole('button', { name: /adopt this prediction/i })).toBeInTheDocument()
  })

  it('clicking "adopt as annotation" copies the prediction into entities + switches to active', () => {
    seedStores({
      activeTab: 'ex_a',
      activeEntities: [{ supplier: 'OLD_ANNOTATION' }],
      predictionsByExp: { 'ex_a': { entities: [{ supplier: 'FROM_EX_A' }] } },
    })
    render(<ReviewOverlay onBack={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /adopt this prediction/i }))
    const s = useReview.getState()
    expect(s.activeTabKey).toBe('active')
    expect(s.entities[0]).toEqual({ supplier: 'FROM_EX_A' })
  })

  it('per-row "use" button on a prediction tab copies the single value into annotation', () => {
    seedStores({
      activeTab: 'ex_a',
      activeEntities: [{ supplier: 'OLD' }],
      predictionsByExp: { 'ex_a': { entities: [{ supplier: 'FROM_EX_A' }] } },
    })
    render(<ReviewOverlay onBack={() => {}} />)
    // hover button is rendered with aria-label "copy {field} to reviewed"
    const useBtn = screen.getByRole('button', { name: /copy supplier to reviewed/i })
    fireEvent.click(useBtn)
    const s = useReview.getState()
    // single-field copy does NOT switch tabs
    expect(s.activeTabKey).toBe('ex_a')
    expect(s.entities[0]).toEqual({ supplier: 'FROM_EX_A' })
  })
})
