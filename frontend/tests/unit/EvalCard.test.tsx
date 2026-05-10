import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import EvalCard, { adaptScoreResult, EvalCardAdapter } from '../../src/components/Chat/EvalCard'
import type { EvalRow } from '../../src/components/Chat/EvalCard'

// ── fixture rows ──────────────────────────────────────────────────────────

const rows: EvalRow[] = [
  { f: 'invoice_number', p: 0.92, r: 0.89, f1: 0.905, n: 44, tone: 'ok' },
  { f: 'vendor_name',    p: 0.78, r: 0.70, f1: 0.738, n: 44, tone: 'mid', err: 'Ambiguous vendor aliases confuse the model.' },
  { f: 'total_amount',   p: 0.55, r: 0.50, f1: 0.524, n: 44, tone: 'bad' },
]

// ── EvalCard unit tests ───────────────────────────────────────────────────

describe('EvalCard', () => {
  it('header renders overall f1 score and scoredAt', () => {
    render(<EvalCard rows={rows} scoredAt="2 hours ago" overall={0.914} />)
    expect(screen.getByText(/0\.914/)).toBeInTheDocument()
    expect(screen.getByText('2 hours ago')).toBeInTheDocument()
    expect(screen.getByText('eval result')).toBeInTheDocument()
  })

  it('header row renders column labels', () => {
    render(<EvalCard rows={rows} scoredAt="just now" overall={0.8} />)
    expect(screen.getByText('field')).toBeInTheDocument()
    // P, R, F1 column headers appear in the head row
    const headRow = screen.getByText('field').closest('.eval-row')
    expect(headRow).toHaveClass('head')
    expect(headRow?.textContent).toContain('P')
    expect(headRow?.textContent).toContain('R')
    expect(headRow?.textContent).toContain('F1')
  })

  it('renders field names and formatted numbers', () => {
    render(<EvalCard rows={rows} scoredAt="just now" overall={0.8} />)
    expect(screen.getByText('invoice_number')).toBeInTheDocument()
    expect(screen.getByText('vendor_name')).toBeInTheDocument()
    expect(screen.getByText('total_amount')).toBeInTheDocument()
    // precision values
    expect(screen.getByText('0.92')).toBeInTheDocument()
    expect(screen.getByText('0.78')).toBeInTheDocument()
  })

  it('applies correct tone class to f1 cell', () => {
    render(<EvalCard rows={rows} scoredAt="just now" overall={0.7} />)
    // ok tone (invoice_number f1=0.905)
    const okCells = document.querySelectorAll('.num.f1.ok')
    expect(okCells.length).toBeGreaterThan(0)
    // mid tone (vendor_name f1=0.738)
    const midCells = document.querySelectorAll('.num.f1.mid')
    expect(midCells.length).toBeGreaterThan(0)
    // bad tone (total_amount f1=0.524)
    const badCells = document.querySelectorAll('.num.f1.bad')
    expect(badCells.length).toBeGreaterThan(0)
  })

  it('click on row with err expands error explanation', () => {
    render(<EvalCard rows={rows} scoredAt="just now" overall={0.7} />)
    // "▾ explain" hint is visible
    expect(screen.getByText(/explain/)).toBeInTheDocument()
    // expansion row is not yet visible
    expect(screen.queryByText(/Ambiguous vendor/)).toBeNull()
    // click the vendor_name row
    const vendorRow = screen.getByText('vendor_name').closest('.eval-row')!
    fireEvent.click(vendorRow)
    // explanation appears
    expect(screen.getByText(/Ambiguous vendor aliases confuse the model/)).toBeInTheDocument()
  })

  it('click same row again collapses explanation', () => {
    render(<EvalCard rows={rows} scoredAt="just now" overall={0.7} />)
    const vendorRow = screen.getByText('vendor_name').closest('.eval-row')!
    fireEvent.click(vendorRow)
    expect(screen.getByText(/Ambiguous vendor/)).toBeInTheDocument()
    fireEvent.click(vendorRow)
    expect(screen.queryByText(/Ambiguous vendor/)).toBeNull()
  })

  it('rows without err do not expand on click', () => {
    render(<EvalCard rows={rows} scoredAt="just now" overall={0.7} />)
    const invoiceRow = screen.getByText('invoice_number').closest('.eval-row')!
    fireEvent.click(invoiceRow)
    // no expansion appears; no extra content
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

  it('returns null when macro_f1 missing', () => {
    expect(adaptScoreResult({ per_field: [] })).toBeNull()
  })

  it('parses a JSON string result', () => {
    const raw = JSON.stringify({ macro_f1: 0.75 })
    const result = adaptScoreResult(raw)
    expect(result).not.toBeNull()
    expect(result!.overall).toBe(0.75)
  })

  it('maps per_field to EvalRow array with correct tone', () => {
    const raw = {
      macro_f1: 0.85,
      per_field: [
        { field: 'amount', precision: 0.9, recall: 0.88, f1: 0.89, support: 10 },
        { field: 'date',   precision: 0.7, recall: 0.65, f1: 0.674, support: 10 },
        { field: 'ref',    precision: 0.4, recall: 0.5,  f1: 0.444, support: 10 },
      ],
    }
    const result = adaptScoreResult(raw)!
    expect(result.rows).toHaveLength(3)
    expect(result.rows[0].tone).toBe('ok')
    expect(result.rows[1].tone).toBe('mid')
    expect(result.rows[2].tone).toBe('bad')
  })

  it('includes error_explanation in err field', () => {
    const raw = {
      macro_f1: 0.6,
      per_field: [
        { field: 'x', precision: 0.5, recall: 0.5, f1: 0.5, support: 5, error_explanation: 'model confused' },
      ],
    }
    const result = adaptScoreResult(raw)!
    expect(result.rows[0].err).toBe('model confused')
  })

  it('uses scored_at when present, fallback to "just now"', () => {
    const withTs = adaptScoreResult({ macro_f1: 0.9, scored_at: '2026-01-01T00:00:00Z' })
    expect(withTs!.scoredAt).toBe('2026-01-01T00:00:00Z')
    const noTs = adaptScoreResult({ macro_f1: 0.9 })
    expect(noTs!.scoredAt).toBe('just now')
  })

  it('handles empty per_field gracefully', () => {
    const result = adaptScoreResult({ macro_f1: 0.5, per_field: [] })
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
            macro_f1: 0.88,
            per_field: [
              { field: 'vendor', precision: 0.9, recall: 0.9, f1: 0.9, support: 20 },
            ],
          },
          ok: true,
        }}
      />,
    )
    expect(screen.getByTestId('eval-card')).toBeInTheDocument()
    expect(screen.getByText(/0\.880/)).toBeInTheDocument()
    expect(screen.getByText('vendor')).toBeInTheDocument()
  })

  it('falls back to plain ToolCall when no per_field', () => {
    render(
      <EvalCardAdapter
        call={{
          ...baseCall,
          tool_result: { macro_f1: 0.72 },
          ok: true,
        }}
      />,
    )
    expect(screen.queryByTestId('eval-card')).toBeNull()
    // ToolCall renders the tool name without the prefix
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
