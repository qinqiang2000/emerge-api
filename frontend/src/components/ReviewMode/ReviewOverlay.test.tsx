// The tab strip's model name is *resolved* here, not in ExperimentTabStrip:
// ReviewOverlay folds the models store into the `modelLabels` map the strip
// consumes. ExperimentTabStrip.test.tsx takes that map as a prop, so it can't
// see which ModelConfig field the map is built from — the regression this file
// guards lives one level up.
//
// Regression: two ModelConfigs may wrap the SAME `provider_model_id` and differ
// only in `params` (e.g. reasoning effort). Keying `modelLabels` on
// provider_model_id collapsed both experiment tabs onto one identical name, so
// the reviewer couldn't tell two side-by-side result sets apart. The map must
// key on the config's own `label`.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import ReviewOverlay from './ReviewOverlay'
import { useDocs } from '../../stores/docs'
import { useExperiments } from '../../stores/experiments'
import { useModels, type ModelRow } from '../../stores/models'
import { useReview } from '../../stores/review'
import { useSchema } from '../../stores/schema'
import type { ExperimentSummary } from '../../types/review'

// Heavy leaves of the overlay — none of them touch the tab strip, and both the
// PDF viewer and the chat column fetch on mount.
vi.mock('./PdfViewer', () => ({ default: () => <div data-testid="pdf-viewer" /> }))
vi.mock('./FieldEditor', () => ({ default: () => <div data-testid="field-editor" /> }))
vi.mock('./ReviewChatColumn', () => ({
  default: () => <div data-testid="review-chat" />,
  readRevChatWidth: () => 360,
  writeRevChatWidth: () => {},
}))

const PID = 'us-invoice'
const DOC = 'acme-0042.pdf'

// The real pair from the models registry: same underlying model, different
// reasoning effort, therefore two ModelConfigs sharing one provider_model_id.
const MODELS: ModelRow[] = [
  {
    model_id: 'm_3nb5v1624kvx',
    label: 'gpt-5.6-terra (default)',
    provider: 'openai',
    provider_model_id: 'openai.gpt-5.6-terra',
    is_active: true,
    created_at: '2026-07-07T02:10:00Z',
  },
  {
    model_id: 'm_5aohh29gyz6i',
    label: 'gpt-5.6-terra (low)',
    provider: 'openai',
    provider_model_id: 'openai.gpt-5.6-terra',
    is_active: false,
    created_at: '2026-07-07T02:12:00Z',
  },
]

const EXPERIMENTS: ExperimentSummary[] = [
  {
    experiment_id: 'ex_default_effort',
    label: 'Baseline v3 × gpt-5.6-terra (default)',
    prompt_id: 'pr_baseline',
    prompt_version: 3,
    model_id: 'm_3nb5v1624kvx',
    status: 'ran',
    created_at: '2026-07-07T02:20:00Z',
    score: 0.81,
  },
  {
    experiment_id: 'ex_low_effort',
    label: 'Baseline v3 × gpt-5.6-terra (low)',
    prompt_id: 'pr_baseline',
    prompt_version: 3,
    model_id: 'm_5aohh29gyz6i',
    status: 'ran',
    created_at: '2026-07-07T02:21:00Z',
    score: 0.77,
  },
]

function seed() {
  useModels.setState({ list: { [PID]: MODELS }, activeByProject: {}, loading: {} })
  useExperiments.setState({ list: { [PID]: EXPERIMENTS }, loading: {} })
  useSchema.setState({ byProject: { [PID]: [] }, loading: {} })
  useDocs.setState({
    byProject: {
      [PID]: [{
        filename: DOC,
        ext: 'pdf',
        page_count: 1,
        sha256: 'deadbeef',
        uploaded_at: '2026-07-07T02:00:00Z',
        original_name: DOC,
        has_prediction: true,
        has_reviewed: false,
      }],
    },
    loading: false,
  })
  useReview.setState({
    activeProjectId: PID,
    activeFilename: DOC,
    activeTabKey: 'active',
    entities: [],
    // Pre-seeded so the eager per-experiment prediction probe short-circuits
    // (`experimentId in predictionsByExp`) and both tabs stay visible.
    predictionsByExp: Object.fromEntries(
      EXPERIMENTS.map((e) => [e.experiment_id, { entities: [] }]),
    ),
  })
}

/** Visible model names, tab order preserved. The ✏ annotation tab has no
 *  `.rev-tab-model` node, so this is exactly the experiment tabs' top line. */
function tabModelNames(container: HTMLElement): (string | null)[] {
  return Array.from(container.querySelectorAll('.rev-tab-model')).map((n) => n.textContent)
}

describe('ReviewOverlay → modelLabels', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    // Guard: nothing in this render should hit the network. A controlled 404
    // beats an unresolvable request against the dev proxy.
    vi.spyOn(window, 'fetch').mockResolvedValue(
      new Response('{}', { status: 404, headers: { 'Content-Type': 'application/json' } }),
    )
    seed()
  })

  it('names two ModelConfigs that share a provider_model_id distinctly', () => {
    const { container } = render(<ReviewOverlay onBack={vi.fn()} rightHidden />)

    expect(tabModelNames(container)).toEqual([
      'gpt-5.6-terra (default)',
      'gpt-5.6-terra (low)',
    ])
    // The shared provider_model_id must never be what the chip shows — it's
    // identical for both configs and so names neither of them.
    expect(screen.queryByText('openai.gpt-5.6-terra')).not.toBeInTheDocument()
  })

  it('pairs each experiment tab with its own model config', () => {
    render(<ReviewOverlay onBack={vi.fn()} rightHidden />)

    // `title` is `${model} · ${prompt}` — asserts the mapping is per-model_id,
    // not merely that both names appear somewhere in the strip.
    expect(
      screen.getByTitle('gpt-5.6-terra (default) · Baseline v3'),
    ).toBeInTheDocument()
    expect(
      screen.getByTitle('gpt-5.6-terra (low) · Baseline v3'),
    ).toBeInTheDocument()
  })
})
