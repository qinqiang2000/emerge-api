import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import EvalCard, { adaptScoreResult, EvalCardAdapter } from '../../src/components/Chat/EvalCard'
import type { EvalRow } from '../../src/components/Chat/EvalCard'

// ── fixture rows (M12.x — accuracy shape) ─────────────────────────────────

const rows: EvalRow[] = [
  {
    f: 'invoice_number', accuracy: 0.95, correct: 42, total: 44,
    nAbsentBoth: 0, notApplicable: false, tone: 'ok',
  },
  {
    f: 'vendor_name', accuracy: 0.80, correct: 35, total: 44,
    nAbsentBoth: 0, notApplicable: false, tone: 'mid',
    err: 'Ambiguous vendor aliases confuse the model.',
  },
  {
    f: 'total_amount', accuracy: 0.55, correct: 24, total: 44,
    nAbsentBoth: 0, notApplicable: false, tone: 'bad',
  },
]

// ── EvalCard unit tests ───────────────────────────────────────────────────

describe('EvalCard', () => {
  it('header renders field accuracy headline + scoredAt', () => {
    render(<EvalCard rows={rows} scoredAt="2 hours ago" overall={0.914} />)
    // M12.x — overall renders as `field acc 91.4%`.
    expect(screen.getByText(/91\.4%/)).toBeInTheDocument()
    expect(screen.getByText('2 hours ago')).toBeInTheDocument()
    expect(screen.getByText('eval result')).toBeInTheDocument()
  })

  it('header row renders just the accuracy column (no P/R/F1)', () => {
    render(<EvalCard rows={rows} scoredAt="just now" overall={0.8} />)
    expect(screen.getByText('field')).toBeInTheDocument()
    const headRow = screen.getByText('field').closest('.eval-row')
    expect(headRow).toHaveClass('head')
    expect(headRow?.textContent).toContain('accuracy')
    // No precision/recall/f1 columns anymore.
    expect(headRow?.textContent).not.toContain('P')
    expect(headRow?.textContent).not.toContain('R')
    expect(headRow?.textContent).not.toContain('F1')
  })

  it('renders field names and accuracy percentages', () => {
    // Use a distinct headline so per-row `80.0%` doesn't collide with it.
    render(<EvalCard rows={rows} scoredAt="just now" overall={0.77} />)
    expect(screen.getByText('invoice_number')).toBeInTheDocument()
    expect(screen.getByText('vendor_name')).toBeInTheDocument()
    expect(screen.getByText('total_amount')).toBeInTheDocument()
    expect(screen.getByText('95.0%')).toBeInTheDocument()
    expect(screen.getByText('80.0%')).toBeInTheDocument()
    expect(screen.getByText('55.0%')).toBeInTheDocument()
  })

  it('applies correct tone class to accuracy cell', () => {
    render(<EvalCard rows={rows} scoredAt="just now" overall={0.7} />)
    // ok tone (invoice_number acc=0.95)
    const okCells = document.querySelectorAll('.num.acc.ok')
    expect(okCells.length).toBeGreaterThan(0)
    // mid tone (vendor_name acc=0.80)
    const midCells = document.querySelectorAll('.num.acc.mid')
    expect(midCells.length).toBeGreaterThan(0)
    // bad tone (total_amount acc=0.55)
    const badCells = document.querySelectorAll('.num.acc.bad')
    expect(badCells.length).toBeGreaterThan(0)
  })

  it('not_applicable row renders em-dash, never red 0%', () => {
    const napRows: EvalRow[] = [
      {
        f: 'rare_field', accuracy: null, correct: 0, total: 0,
        nAbsentBoth: 0, notApplicable: true, tone: 'mid',
      },
    ]
    render(<EvalCard rows={napRows} scoredAt="just now" overall={0.9} />)
    expect(screen.getByText('—')).toBeInTheDocument()
    // and no `.num.acc.bad` row for this field.
    const badCells = document.querySelectorAll('.num.acc.bad')
    expect(badCells.length).toBe(0)
  })

  it('click on row with err expands error explanation', () => {
    render(<EvalCard rows={rows} scoredAt="just now" overall={0.7} />)
    expect(screen.getByText(/explain/)).toBeInTheDocument()
    expect(screen.queryByText(/Ambiguous vendor/)).toBeNull()
    const vendorRow = screen.getByText('vendor_name').closest('.eval-row')!
    fireEvent.click(vendorRow)
    expect(screen.getByText(/Ambiguous vendor aliases confuse the model/)).toBeInTheDocument()
  })

  it('rows without err do not expand on click', () => {
    render(<EvalCard rows={rows} scoredAt="just now" overall={0.7} />)
    const invoiceRow = screen.getByText('invoice_number').closest('.eval-row')!
    fireEvent.click(invoiceRow)
    expect(document.querySelectorAll('.eval-row.expand').length).toBe(0)
  })

  it('renders placeholder when rows array is empty', () => {
    render(<EvalCard rows={[]} scoredAt="just now" overall={0.5} />)
    expect(screen.getByText(/per-field breakdown not available/)).toBeInTheDocument()
  })
})

// ── adaptScoreResult ──────────────────────────────────────────────────────

describe('adaptScoreResult', () => {
  it('returns null for non-object input', () => {
    expect(adaptScoreResult(null)).toBeNull()
    expect(adaptScoreResult('not json')).toBeNull()
    expect(adaptScoreResult(42)).toBeNull()
  })

  it('returns null when neither field_accuracy_macro nor macro_f1 present', () => {
    expect(adaptScoreResult({ per_field: [] })).toBeNull()
  })

  it('parses a JSON string result (M12.x shape)', () => {
    const raw = JSON.stringify({ field_accuracy_macro: 0.75, per_field: [] })
    const result = adaptScoreResult(raw)
    expect(result).not.toBeNull()
    expect(result!.overall).toBe(0.75)
  })

  it('falls back to macro_f1 when only legacy summary available', () => {
    const raw = JSON.stringify({ macro_f1: 0.62, per_field: [] })
    const result = adaptScoreResult(raw)
    expect(result).not.toBeNull()
    expect(result!.overall).toBe(0.62)
  })

  it('synthesizes overall from per-field accuracy when headline missing', () => {
    // No field_accuracy_macro key on the input — must derive from per_field.
    const raw = {
      macro_f1: null,
      per_field: [
        { field: 'a', accuracy: 0.8, correct: 4, total: 5, n_absent_both: 0, not_applicable: false },
        { field: 'b', accuracy: 1.0, correct: 5, total: 5, n_absent_both: 0, not_applicable: false },
        // not_applicable should be excluded from the macro mean.
        { field: 'c', accuracy: 0, correct: 0, total: 0, n_absent_both: 0, not_applicable: true },
      ],
    }
    const result = adaptScoreResult(raw)
    expect(result).not.toBeNull()
    expect(result!.overall).toBeCloseTo(0.9, 3)
  })

  it('maps per_field accuracy to EvalRow tone correctly', () => {
    const raw = {
      field_accuracy_macro: 0.85,
      per_field: [
        { field: 'amount', accuracy: 0.92, correct: 9, total: 10, n_absent_both: 0, not_applicable: false },
        { field: 'date', accuracy: 0.80, correct: 8, total: 10, n_absent_both: 2, not_applicable: false },
        { field: 'ref', accuracy: 0.40, correct: 4, total: 10, n_absent_both: 0, not_applicable: false },
      ],
    }
    const result = adaptScoreResult(raw)!
    expect(result.rows).toHaveLength(3)
    expect(result.rows[0].tone).toBe('ok')
    expect(result.rows[1].tone).toBe('mid')
    expect(result.rows[2].tone).toBe('bad')
  })

  it('absent_both fields with all cells absent show accuracy=1.0 (M12.x rule)', () => {
    // Mirrors the dogfood landmine: invoice_code with 21 cells all
    // absent_both — must come out as 100% accuracy, not the old F1=0 trap.
    const raw = {
      field_accuracy_macro: null,
      per_field: [
        { field: 'invoice_code', accuracy: 1.0, correct: 21, total: 21, n_absent_both: 21, not_applicable: false },
      ],
    }
    const result = adaptScoreResult(raw)!
    expect(result.rows[0].accuracy).toBe(1.0)
    expect(result.rows[0].tone).toBe('ok')
    expect(result.rows[0].nAbsentBoth).toBe(21)
  })

  it('includes error_explanation in err field', () => {
    const raw = {
      field_accuracy_macro: 0.6,
      per_field: [
        { field: 'x', accuracy: 0.5, correct: 5, total: 10, n_absent_both: 0, not_applicable: false, error_explanation: 'model confused' },
      ],
    }
    const result = adaptScoreResult(raw)!
    expect(result.rows[0].err).toBe('model confused')
  })

  it('reads `ts` (the backend field name) as the scoredAt fallback', () => {
    const out = adaptScoreResult(JSON.stringify({
      n_docs: 6, n_reviewed: 5, field_accuracy_macro: 0.971, errors: [],
      ts: '2026-05-11T07-04-00Z', schema_field_count: 7,
      per_field: [
        { field: 'invoice_number', accuracy: 1.0, correct: 5, total: 5, n_absent_both: 0, not_applicable: false },
        { field: 'customer_name', accuracy: 0.8, correct: 4, total: 5, n_absent_both: 0, not_applicable: false },
      ],
    }))
    expect(out).not.toBeNull()
    expect(out!.overall).toBeCloseTo(0.971)
    expect(out!.rows[1]).toMatchObject({ f: 'customer_name', accuracy: 0.8, correct: 4, total: 5 })
    expect(out!.scoredAt).toBe('2026-05-11T07-04-00Z')
  })

  it('handles empty per_field gracefully', () => {
    const result = adaptScoreResult({ field_accuracy_macro: 0.5, per_field: [] })
    expect(result).not.toBeNull()
    expect(result!.rows).toHaveLength(0)
  })
})

// ── EvalCardAdapter integration ───────────────────────────────────────────

describe('EvalCardAdapter', () => {
  const baseCall = {
    type: 'tool_call' as const,
    tool_use_id: 'tu_1',
    tool_name: 'mcp__emerge_tools__score',
    tool_input: { project_id: 'p_x', version: 1 },
    ok: true as boolean,
  }

  it('renders EvalCard when per_field data present', () => {
    render(
      <EvalCardAdapter
        call={{
          ...baseCall,
          tool_result: {
            field_accuracy_macro: 0.88,
            per_field: [
              { field: 'vendor', accuracy: 0.9, correct: 18, total: 20, n_absent_both: 0, not_applicable: false },
            ],
          },
          ok: true,
        }}
      />,
    )
    expect(screen.getByTestId('eval-card')).toBeInTheDocument()
    // Headline renders 88.0%.
    expect(screen.getByText(/88\.0%/)).toBeInTheDocument()
    expect(screen.getByText('vendor')).toBeInTheDocument()
  })

  it('falls back to plain ToolCall when no per_field', () => {
    render(
      <EvalCardAdapter
        call={{
          ...baseCall,
          tool_result: { field_accuracy_macro: 0.72 },
          ok: true,
        }}
      />,
    )
    expect(screen.queryByTestId('eval-card')).toBeNull()
    expect(screen.getByText('score')).toBeInTheDocument()
  })

  it('falls back to plain ToolCall when result is null (running)', () => {
    render(
      <EvalCardAdapter
        call={{
          ...baseCall,
          tool_result: undefined,
          ok: true,
        }}
      />,
    )
    expect(screen.queryByTestId('eval-card')).toBeNull()
    expect(screen.getByText('score')).toBeInTheDocument()
  })
})
