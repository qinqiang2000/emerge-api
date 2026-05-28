// BenchMatrix — the experiments × fields table at the heart of bench.
//
// Cell coloring policy (mirrors design demo cellTint):
//   r >= 0.9   → "ok"
//   r >= 0.75  → "mid"
//   r <  0.75  → "bad"
//   c == null  → "empty"
// Hover dim:
//   when `hovered.kind === 'prompt'`, every row whose prompt_id differs
//   carries a `.dimmed` class — same for `kind === 'model'`.
import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

import BenchMatrix from '../BenchMatrix'
import type { BenchPromptAxisItem, BenchModelAxisItem, BenchRow } from '../../../types/bench'

const PROMPTS: BenchPromptAxisItem[] = [
  { id: 'pr_a', label: 'prompt-a', is_active: true, refs: 2 },
  { id: 'pr_b', label: 'prompt-b', is_active: false, refs: 1 },
]
const MODELS: BenchModelAxisItem[] = [
  { id: 'm_x', label: 'model-x', provider_model_id: 'mx-1', is_active: true, refs: 2 },
  { id: 'm_y', label: 'model-y', provider_model_id: 'my-1', is_active: false, refs: 1 },
]

function row(over: Partial<BenchRow>): BenchRow {
  return {
    id: 'ex_test',
    kind: 'experiment',
    prompt_id: 'pr_a',
    model_id: 'm_x',
    status: 'ran',
    is_active: false,
    score: 0.8,
    delta: null,
    ran_at: '2026-05-25T12:00:00Z',
    summary_ts: '2026-05-25T120000Z',
    cells: {},
    ...over,
  }
}

const FIELDS = ['invoice_number', 'issuer', 'total_amount']

describe('BenchMatrix', () => {
  it('renders one <tr.b-row> per data row (plus the create-experiment row)', () => {
    const rows = [
      row({ id: 'r1', prompt_id: 'pr_a', model_id: 'm_x' }),
      row({ id: 'r2', prompt_id: 'pr_b', model_id: 'm_x' }),
      row({ id: 'r3', prompt_id: 'pr_a', model_id: 'm_y' }),
    ]
    const { container } = render(
      <BenchMatrix
        rows={rows}
        fields={FIELDS}
        prompts={PROMPTS}
        models={MODELS}
        selectedIds={new Set()}
        hovered={null}
        onToggleSelect={() => {}}
        onOpenRow={() => {}}
        onPromote={() => {}}
        onRunEval={() => {}}
      />,
    )
    expect(container.querySelectorAll('tr.b-row')).toHaveLength(3)
  })

  it('high cell ≥0.9 → ok class, mid 0.75-0.9 → mid, low → bad, null → empty', () => {
    const rows = [
      row({
        id: 'r1',
        cells: {
          invoice_number: { correct: 50, total: 50, strip: [1, 1, 1, 1, 1, 1] },     // 1.0 → ok
          issuer:         { correct: 40, total: 50, strip: [1, 1, 1, 1, 0, 0] },     // 0.8 → mid
          total_amount:   { correct: 25, total: 50, strip: [1, 0, 0, 0, 0, 1] },     // 0.5 → bad
        },
      }),
    ]
    const { container } = render(
      <BenchMatrix
        rows={rows}
        fields={FIELDS}
        prompts={PROMPTS}
        models={MODELS}
        selectedIds={new Set()}
        hovered={null}
        onToggleSelect={() => {}}
        onOpenRow={() => {}}
        onPromote={() => {}}
        onRunEval={() => {}}
      />,
    )
    const cells = container.querySelectorAll('td.b-cell')
    // Cells render in `fields` order: invoice_number (ok), issuer (mid), total_amount (bad)
    expect(cells[0].className).toMatch(/b-cell-ok/)
    expect(cells[1].className).toMatch(/b-cell-mid/)
    expect(cells[2].className).toMatch(/b-cell-bad/)
  })

  it('null cell (field absent from row.cells) → b-cell-empty + em-dash placeholder', () => {
    const rows = [
      row({
        id: 'r1',
        cells: {
          // intentionally omit `issuer` + `total_amount`
          invoice_number: { correct: 50, total: 50, strip: [1, 1, 1, 1, 1, 1] },
        },
      }),
    ]
    const { container } = render(
      <BenchMatrix
        rows={rows}
        fields={FIELDS}
        prompts={PROMPTS}
        models={MODELS}
        selectedIds={new Set()}
        hovered={null}
        onToggleSelect={() => {}}
        onOpenRow={() => {}}
        onPromote={() => {}}
        onRunEval={() => {}}
      />,
    )
    const cells = container.querySelectorAll('td.b-cell')
    expect(cells[1].className).toMatch(/b-cell-empty/)
    expect(cells[2].className).toMatch(/b-cell-empty/)
    // em-dash placeholder
    expect(cells[1].textContent).toContain('—')
  })

  it('hover prompt chip → rows with a different prompt_id get .dimmed', () => {
    const rows = [
      row({ id: 'r1', prompt_id: 'pr_a', model_id: 'm_x' }),
      row({ id: 'r2', prompt_id: 'pr_b', model_id: 'm_x' }),
      row({ id: 'r3', prompt_id: 'pr_a', model_id: 'm_y' }),
    ]
    const { container } = render(
      <BenchMatrix
        rows={rows}
        fields={FIELDS}
        prompts={PROMPTS}
        models={MODELS}
        selectedIds={new Set()}
        hovered={{ kind: 'prompt', id: 'pr_a' }}
        onToggleSelect={() => {}}
        onOpenRow={() => {}}
        onPromote={() => {}}
        onRunEval={() => {}}
      />,
    )
    const trs = container.querySelectorAll('tr.b-row')
    expect(trs[0].className).not.toMatch(/\bdimmed\b/)  // pr_a matches
    expect(trs[1].className).toMatch(/\bdimmed\b/)       // pr_b doesn't
    expect(trs[2].className).not.toMatch(/\bdimmed\b/)   // pr_a matches
  })

  it('hover model chip → rows with a different model_id get .dimmed', () => {
    const rows = [
      row({ id: 'r1', prompt_id: 'pr_a', model_id: 'm_x' }),
      row({ id: 'r2', prompt_id: 'pr_a', model_id: 'm_y' }),
    ]
    const { container } = render(
      <BenchMatrix
        rows={rows}
        fields={FIELDS}
        prompts={PROMPTS}
        models={MODELS}
        selectedIds={new Set()}
        hovered={{ kind: 'model', id: 'm_x' }}
        onToggleSelect={() => {}}
        onOpenRow={() => {}}
        onPromote={() => {}}
        onRunEval={() => {}}
      />,
    )
    const trs = container.querySelectorAll('tr.b-row')
    expect(trs[0].className).not.toMatch(/\bdimmed\b/)
    expect(trs[1].className).toMatch(/\bdimmed\b/)
  })

  it('row click invokes onOpenRow with the BenchRow', () => {
    const onOpenRow = vi.fn()
    const r1 = row({ id: 'r1' })
    const { container } = render(
      <BenchMatrix
        rows={[r1]}
        fields={FIELDS}
        prompts={PROMPTS}
        models={MODELS}
        selectedIds={new Set()}
        hovered={null}
        onToggleSelect={() => {}}
        onOpenRow={onOpenRow}
        onPromote={() => {}}
        onRunEval={() => {}}
      />,
    )
    const tr = container.querySelector('tr.b-row') as HTMLTableRowElement
    fireEvent.click(tr)
    expect(onOpenRow).toHaveBeenCalledWith(r1)
  })

  it('checkbox cell click invokes onToggleSelect(row.id) without firing onOpenRow', () => {
    const onOpenRow = vi.fn()
    const onToggleSelect = vi.fn()
    const r1 = row({ id: 'r1' })
    const { container } = render(
      <BenchMatrix
        rows={[r1]}
        fields={FIELDS}
        prompts={PROMPTS}
        models={MODELS}
        selectedIds={new Set()}
        hovered={null}
        onToggleSelect={onToggleSelect}
        onOpenRow={onOpenRow}
        onPromote={() => {}}
        onRunEval={() => {}}
      />,
    )
    const pickCell = container.querySelector('td.b-row-pick') as HTMLTableCellElement
    fireEvent.click(pickCell)
    expect(onToggleSelect).toHaveBeenCalledWith('r1')
    expect(onOpenRow).not.toHaveBeenCalled()
  })

  it('selected row carries .selected class and the checkbox renders ✓', () => {
    const r1 = row({ id: 'r1' })
    const { container } = render(
      <BenchMatrix
        rows={[r1]}
        fields={FIELDS}
        prompts={PROMPTS}
        models={MODELS}
        selectedIds={new Set(['r1'])}
        hovered={null}
        onToggleSelect={() => {}}
        onOpenRow={() => {}}
        onPromote={() => {}}
        onRunEval={() => {}}
      />,
    )
    const tr = container.querySelector('tr.b-row') as HTMLTableRowElement
    expect(tr.className).toMatch(/\bselected\b/)
    expect(within(tr).getByText('✓')).toBeInTheDocument()
  })

  it('row with null score → status "draft" + a "run eval" action button', () => {
    const r1 = row({ id: 'r1', score: null, status: 'draft' })
    render(
      <BenchMatrix
        rows={[r1]}
        fields={FIELDS}
        prompts={PROMPTS}
        models={MODELS}
        selectedIds={new Set()}
        hovered={null}
        onToggleSelect={() => {}}
        onOpenRow={() => {}}
        onPromote={() => {}}
        onRunEval={vi.fn()}
      />,
    )
    expect(screen.getByText(/run eval/i)).toBeInTheDocument()
  })

  it('row with score and is_active=true → "active" badge, no promote button', () => {
    const r1 = row({ id: 'r1', is_active: true, score: 0.9 })
    render(
      <BenchMatrix
        rows={[r1]}
        fields={FIELDS}
        prompts={PROMPTS}
        models={MODELS}
        selectedIds={new Set()}
        hovered={null}
        onToggleSelect={() => {}}
        onOpenRow={() => {}}
        onPromote={() => {}}
        onRunEval={() => {}}
      />,
    )
    expect(screen.getByText(/^active$/i)).toBeInTheDocument()
    expect(screen.queryByText(/promote/i)).not.toBeInTheDocument()
  })

  it('non-active scored row → "promote" button, click invokes onPromote(row.id)', () => {
    const onPromote = vi.fn()
    const r1 = row({ id: 'r1', is_active: false, score: 0.7 })
    render(
      <BenchMatrix
        rows={[r1]}
        fields={FIELDS}
        prompts={PROMPTS}
        models={MODELS}
        selectedIds={new Set()}
        hovered={null}
        onToggleSelect={() => {}}
        onOpenRow={() => {}}
        onPromote={onPromote}
        onRunEval={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /promote/i }))
    expect(onPromote).toHaveBeenCalledWith('r1')
  })

  it('promote-button click does not propagate to onOpenRow', () => {
    const onPromote = vi.fn()
    const onOpenRow = vi.fn()
    const r1 = row({ id: 'r1', is_active: false, score: 0.7 })
    render(
      <BenchMatrix
        rows={[r1]}
        fields={FIELDS}
        prompts={PROMPTS}
        models={MODELS}
        selectedIds={new Set()}
        hovered={null}
        onToggleSelect={() => {}}
        onOpenRow={onOpenRow}
        onPromote={onPromote}
        onRunEval={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /promote/i }))
    expect(onPromote).toHaveBeenCalledTimes(1)
    expect(onOpenRow).not.toHaveBeenCalled()
  })

  it('renders the empty "create experiment" row beneath the data rows', () => {
    render(
      <BenchMatrix
        rows={[row({ id: 'r1' })]}
        fields={FIELDS}
        prompts={PROMPTS}
        models={MODELS}
        selectedIds={new Set()}
        hovered={null}
        onToggleSelect={() => {}}
        onOpenRow={() => {}}
        onPromote={() => {}}
        onRunEval={() => {}}
      />,
    )
    expect(screen.getByText(/create experiment/i)).toBeInTheDocument()
  })
})
