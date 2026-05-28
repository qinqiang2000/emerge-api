// BenchDiff — 2-row comparison modal (per-field Δ bars + prompt line-diff).
//
// Diff modal contract (per plan T7):
//   - header chip "COMPARE" + title `{basePromptLabel} · {baseModelShort} →
//     {targetPromptLabel} · {targetModelShort}` + ✕ close
//   - summary section: score Δ + "axes changed" pills (prompt / model / none)
//   - per-field Δ rows: name · base.correct/total → target.correct/total ·
//     bar (width = |delta|/total) · pill (+N / -N)
//   - prompt text diff section: rendered only when base.prompt_id !==
//     target.prompt_id AND both bodies are ready. Simple line-by-line set
//     membership: `aLines.includes(line)` (no diff-match-patch).
//   - close affordances: ✕ button, backdrop click, Escape key (all → onClose)
//   - footer: close button + copy-as-text placeholder + "promote {label}"
import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import BenchDiff from '../BenchDiff'
import type { BenchRow } from '../../../types/bench'

// Shared fixtures ──────────────────────────────────────────────────────────

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
    summary_ts: '20260525T120000Z',
    cells: {},
    ...over,
  }
}

const PROMPT_LABELS = { pr_a: 'baseline', pr_b: 'supplier-hint' }
const MODEL_LABELS = { m_x: 'gemini-2.5-flash', m_y: 'claude-sonnet-4-5' }
const FIELDS = ['invoice_number', 'issuer']

describe('BenchDiff', () => {
  // ── 1. different prompt, same model ────────────────────────────────────
  it('different prompt + same model → renders score Δ, prompt axis pill, prompt-text section', () => {
    const base = row({ id: 'r1', prompt_id: 'pr_a', model_id: 'm_x', score: 0.80 })
    const targ = row({ id: 'r2', prompt_id: 'pr_b', model_id: 'm_x', score: 0.90 })
    const { container } = render(
      <BenchDiff
        base={base}
        target={targ}
        basePromptBody="line A\nline B\n"
        targetPromptBody="line A\nline C\n"
        fields={FIELDS}
        promptLabels={PROMPT_LABELS}
        modelLabels={MODEL_LABELS}
        onClose={() => {}}
        onPromote={() => {}}
      />,
    )
    // header chip
    expect(screen.getByText(/COMPARE/i)).toBeInTheDocument()
    // score Δ delta pill — +0.10 (one decimal trail trimmed to .1)
    expect(container.textContent || '').toMatch(/\+0\.1/)
    // axes-changed: prompt pill present, model pill absent, no "none" muted
    const summary = container.querySelector('.b-diff-summary')
    expect(summary?.textContent).toMatch(/prompt/)
    expect(summary?.textContent).not.toMatch(/^model$/m)
    // prompt-text section shows
    expect(container.querySelector('.b-diff-prompt')).not.toBeNull()
  })

  // ── 2. same prompt, different model ────────────────────────────────────
  it('same prompt + different model → axes pill shows "model", no prompt-text section', () => {
    const base = row({ id: 'r1', prompt_id: 'pr_a', model_id: 'm_x', score: 0.80 })
    const targ = row({ id: 'r2', prompt_id: 'pr_a', model_id: 'm_y', score: 0.85 })
    const { container } = render(
      <BenchDiff
        base={base}
        target={targ}
        basePromptBody="anything"
        targetPromptBody="anything"
        fields={FIELDS}
        promptLabels={PROMPT_LABELS}
        modelLabels={MODEL_LABELS}
        onClose={() => {}}
        onPromote={() => {}}
      />,
    )
    const summary = container.querySelector('.b-diff-summary')
    expect(summary?.textContent).toMatch(/model/)
    expect(container.querySelector('.b-diff-prompt')).toBeNull()
  })

  // ── 3. same prompt + same model → "none" ──────────────────────────────
  it('same prompt + same model → axes summary renders the "none" muted marker', () => {
    const base = row({ id: 'r1', prompt_id: 'pr_a', model_id: 'm_x', score: 0.80 })
    const targ = row({ id: 'r2', prompt_id: 'pr_a', model_id: 'm_x', score: 0.85 })
    render(
      <BenchDiff
        base={base}
        target={targ}
        basePromptBody=""
        targetPromptBody=""
        fields={FIELDS}
        promptLabels={PROMPT_LABELS}
        modelLabels={MODEL_LABELS}
        onClose={() => {}}
        onPromote={() => {}}
      />,
    )
    expect(screen.getByText(/^none$/i)).toBeInTheDocument()
  })

  // ── 4. per-field Δ row ─────────────────────────────────────────────────
  it('per-field row renders "5/10 → 8/10" + delta pill +3 + up class on bar', () => {
    const base = row({
      id: 'r1',
      cells: {
        a: { correct: 5, total: 10, strip: [] },
        b: { correct: 5, total: 10, strip: [] },
      },
      score: 0.5,
    })
    const targ = row({
      id: 'r2',
      cells: {
        a: { correct: 8, total: 10, strip: [] },
        b: { correct: 5, total: 10, strip: [] },
      },
      score: 0.65,
    })
    const { container } = render(
      <BenchDiff
        base={base}
        target={targ}
        basePromptBody=""
        targetPromptBody=""
        fields={['a', 'b']}
        promptLabels={PROMPT_LABELS}
        modelLabels={MODEL_LABELS}
        onClose={() => {}}
        onPromote={() => {}}
      />,
    )
    const fieldRows = container.querySelectorAll('.b-diff-frow')
    expect(fieldRows.length).toBe(2)
    // Row 'a' — 5/10 → 8/10, delta +3, up class
    const rowA = fieldRows[0]
    expect(rowA.textContent).toMatch(/5\/10/)
    expect(rowA.textContent).toMatch(/8\/10/)
    expect(rowA.textContent).toMatch(/\+3/)
    expect(rowA.querySelector('.b-diff-bar.up')).not.toBeNull()
    // Row 'b' — delta 0, flat class
    const rowB = fieldRows[1]
    expect(rowB.querySelector('.b-diff-bar.flat')).not.toBeNull()
  })

  // ── 5. promote button → onPromote(target.id) ───────────────────────────
  it('promote button click → onPromote(target.id)', () => {
    const onPromote = vi.fn()
    const base = row({ id: 'r1', prompt_id: 'pr_a', score: 0.80 })
    const targ = row({ id: 'r2', prompt_id: 'pr_b', score: 0.90 })
    render(
      <BenchDiff
        base={base}
        target={targ}
        basePromptBody=""
        targetPromptBody=""
        fields={FIELDS}
        promptLabels={PROMPT_LABELS}
        modelLabels={MODEL_LABELS}
        onClose={() => {}}
        onPromote={onPromote}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /promote/i }))
    expect(onPromote).toHaveBeenCalledWith('r2')
  })

  // ── 6a. ✕ close button → onClose ───────────────────────────────────────
  it('close button click → onClose called once', () => {
    const onClose = vi.fn()
    const base = row({ id: 'r1', prompt_id: 'pr_a' })
    const targ = row({ id: 'r2', prompt_id: 'pr_a' })
    const { container } = render(
      <BenchDiff
        base={base}
        target={targ}
        basePromptBody=""
        targetPromptBody=""
        fields={FIELDS}
        promptLabels={PROMPT_LABELS}
        modelLabels={MODEL_LABELS}
        onClose={onClose}
        onPromote={() => {}}
      />,
    )
    const x = container.querySelector('.b-diff-x') as HTMLButtonElement
    fireEvent.click(x)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  // ── 6b. backdrop click → onClose ───────────────────────────────────────
  it('clicking the backdrop closes; clicking inside the modal does NOT', () => {
    const onClose = vi.fn()
    const base = row({ id: 'r1' })
    const targ = row({ id: 'r2' })
    const { container } = render(
      <BenchDiff
        base={base}
        target={targ}
        basePromptBody=""
        targetPromptBody=""
        fields={FIELDS}
        promptLabels={PROMPT_LABELS}
        modelLabels={MODEL_LABELS}
        onClose={onClose}
        onPromote={() => {}}
      />,
    )
    const backdrop = container.querySelector('.b-diff-back') as HTMLDivElement
    const modal = container.querySelector('.b-diff-modal') as HTMLDivElement
    fireEvent.click(modal)
    expect(onClose).toHaveBeenCalledTimes(0)
    fireEvent.click(backdrop)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  // ── 6c. ESC → onClose ──────────────────────────────────────────────────
  it('Escape keydown → onClose', () => {
    const onClose = vi.fn()
    const base = row({ id: 'r1' })
    const targ = row({ id: 'r2' })
    render(
      <BenchDiff
        base={base}
        target={targ}
        basePromptBody=""
        targetPromptBody=""
        fields={FIELDS}
        promptLabels={PROMPT_LABELS}
        modelLabels={MODEL_LABELS}
        onClose={onClose}
        onPromote={() => {}}
      />,
    )
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  // ── 7. prompt body loading → skeleton ──────────────────────────────────
  it('prompt body null (loading) → skeleton placeholder rendered in prompt-text section', () => {
    const base = row({ id: 'r1', prompt_id: 'pr_a' })
    const targ = row({ id: 'r2', prompt_id: 'pr_b' })
    const { container } = render(
      <BenchDiff
        base={base}
        target={targ}
        basePromptBody={null}
        targetPromptBody={null}
        fields={FIELDS}
        promptLabels={PROMPT_LABELS}
        modelLabels={MODEL_LABELS}
        onClose={() => {}}
        onPromote={() => {}}
      />,
    )
    // section still rendered (different prompt), but body shows loading marker
    const prompt = container.querySelector('.b-diff-prompt')
    expect(prompt).not.toBeNull()
    expect(prompt?.textContent).toMatch(/loading/i)
  })

  // ── 8. prompt line-diff: added + removed ───────────────────────────────
  it('prompt line-diff: target-only line gets added class; base-only line gets removed class', () => {
    const base = row({ id: 'r1', prompt_id: 'pr_a' })
    const targ = row({ id: 'r2', prompt_id: 'pr_b' })
    const { container } = render(
      <BenchDiff
        base={base}
        target={targ}
        basePromptBody="line A\nline B\n"
        targetPromptBody="line A\nline C\n"
        fields={FIELDS}
        promptLabels={PROMPT_LABELS}
        modelLabels={MODEL_LABELS}
        onClose={() => {}}
        onPromote={() => {}}
      />,
    )
    // Target column: "line C" is added
    const targCol = container.querySelector('.b-diff-body.targ')
    const added = targCol?.querySelectorAll('.b-line-added')
    expect(added && added.length).toBeGreaterThan(0)
    const addedText = Array.from(added || []).map(n => (n.textContent || '').trim()).join(' ')
    expect(addedText).toMatch(/line C/)

    // Base column: "line B" is removed (strikethrough)
    const baseCol = container.querySelector('.b-diff-body.base')
    const removed = baseCol?.querySelectorAll('.b-line-removed')
    expect(removed && removed.length).toBeGreaterThan(0)
    const removedText = Array.from(removed || []).map(n => (n.textContent || '').trim()).join(' ')
    expect(removedText).toMatch(/line B/)
  })
})
