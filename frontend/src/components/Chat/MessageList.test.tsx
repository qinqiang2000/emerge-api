// P4 Task 7 — score(kind=) folds score_audit/score_match into one tool name,
// so the tool name alone can no longer pick the chat card. This pins the
// actual component-level dispatch (HoistedToolCard) per kind, so a future
// change that breaks card selection fails a test instead of only silently
// rendering the wrong card (or none) in the browser.
import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { ChatEvent } from '../../types/chat'
import { useProjects } from '../../stores/projects'
import { useReviewBoard } from '../../stores/reviewBoard'
import { HoistedToolCard } from './MessageList'

type ToolCallEvent = Extract<ChatEvent, { type: 'tool_call' }>

function call(tool_input: unknown, tool_result: unknown, tool_name = 'mcp__emerge_tools__score'): ToolCallEvent {
  return {
    type: 'tool_call',
    tool_use_id: 'tu_1',
    tool_name,
    tool_input,
    tool_result,
    ok: true,
  }
}

const EXTRACT_RESULT = JSON.stringify({
  field_accuracy_macro: 0.92,
  doc_accuracy: 0.9,
  per_field: [
    { field: 'invoice_no', accuracy: 1.0, correct: 1, total: 1, n_absent_both: 0, not_applicable: false },
  ],
  ts: '2026-08-16T00-00-00Z',
})

const AUDIT_RESULT = JSON.stringify({
  run_id: 'au_1',
  reviewed: 3,
  accuracy: 0.6667,
  precision: 1.0,
  recall: 0.5,
  unclear: 1,
  per_rule: [
    { rule: '甲方为环胜', truth: 'pass', predicted: 'pass', correct: true },
    { rule: '盖红章', truth: 'fail', predicted: 'pass', correct: false },
  ],
  unreviewed_rules: [],
})

const MATCH_RESULT = JSON.stringify({
  reviewed: 4,
  per_source: { payments: { precision: 1.0, recall: 0.75 } },
  doc_completeness: 0.8,
})

describe('HoistedToolCard — score(kind=) card selection', () => {
  it('kind absent (default extract) renders EvalCard', () => {
    render(<HoistedToolCard call={call({ slug: 'p_x' }, EXTRACT_RESULT)} />)
    expect(screen.getByTestId('eval-card')).toBeTruthy()
    expect(screen.queryByTestId('audit-score-card')).toBeNull()
  })

  it("kind='extract' renders EvalCard", () => {
    render(<HoistedToolCard call={call({ slug: 'p_x', kind: 'extract' }, EXTRACT_RESULT)} />)
    expect(screen.getByTestId('eval-card')).toBeTruthy()
  })

  it("kind='audit' renders AuditScoreCard, not EvalCard", () => {
    render(<HoistedToolCard call={call({ slug: 'p_x', kind: 'audit' }, AUDIT_RESULT)} />)
    expect(screen.getByTestId('audit-score-card')).toBeTruthy()
    expect(screen.queryByTestId('eval-card')).toBeNull()
  })

  it("kind='match' falls through to the generic tool card (same as score_match pre-merge), not EvalCard or AuditCard", () => {
    render(<HoistedToolCard call={call({ slug: 'p_x', kind: 'match' }, MATCH_RESULT)} />)
    expect(screen.queryByTestId('eval-card')).toBeNull()
    expect(screen.queryByTestId('audit-card')).toBeNull()
    expect(screen.queryByTestId('audit-score-card')).toBeNull()
    // The generic ToolCall row still renders, with the bare tool name.
    expect(screen.getByText('score')).toBeTruthy()
  })

  it('legacy transcript name score_audit (pre-P4-Task-7) still renders AuditScoreCard', () => {
    render(<HoistedToolCard call={call({ slug: 'p_x' }, AUDIT_RESULT, 'mcp__emerge_tools__score_audit')} />)
    expect(screen.getByTestId('audit-score-card')).toBeTruthy()
  })

  it('legacy transcript name score_match (pre-P4-Task-7) still falls through to the generic tool card', () => {
    render(<HoistedToolCard call={call({ slug: 'p_x' }, MATCH_RESULT, 'mcp__emerge_tools__score_match')} />)
    expect(screen.queryByTestId('eval-card')).toBeNull()
    expect(screen.queryByTestId('audit-score-card')).toBeNull()
    expect(screen.getByText('score_match')).toBeTruthy()
  })

  it('run_audit (unrelated to the score merge) still renders the audit REPORT card', () => {
    const report = JSON.stringify({
      overall: 'fail',
      checks: [{ rule: '盖红章', status: 'fail', reason: '未见', level: 'critical', decided_by: 'judge' }],
    })
    render(<HoistedToolCard call={call({ slug: 'p_x' }, report, 'mcp__emerge_tools__run_audit')} />)
    expect(screen.getByTestId('audit-card')).toBeTruthy()
  })
})

// P4 Task 10 — render_board(kind=) folds render_audit_board/render_review_
// board, so the tool name alone can no longer pick the card either. Mirrors
// the score(kind=) test block above: pins the actual HoistedToolCard dispatch
// per kind (and per legacy transcript name) so a future change that breaks
// card selection fails a test instead of silently rendering the wrong card
// (or none) in the browser.
const REVIEW_BOARD_PAYLOAD = {
  docs: [
    { id: '2994530', verdict: 'fail' as const, supplier: '安徽晶瑞药业有限公司', amount: '14107.5',
      invoice_no: '263420', memo: '', reason: '维生素B1片数量不符' },
  ],
  html_by_id: { '2994530': '<!doctype html><body>fail</body>' },
  tally: { pass: 0, fail: 1, unclear: 0 },
  model_label: 'deepseek-v4-flash',
}

describe('HoistedToolCard — render_board(kind=) card selection', () => {
  afterEach(() => {
    act(() => {
      useReviewBoard.setState({ byProject: {}, loading: {}, errors: {} })
      useProjects.setState({ selectedSlug: null })
    })
  })

  it("kind='review' renders ReviewBoardCard, not the generic tool card", () => {
    act(() => {
      useProjects.setState({ selectedSlug: 'p1' })
      useReviewBoard.setState({ byProject: { p1: REVIEW_BOARD_PAYLOAD } })
    })
    render(
      <HoistedToolCard
        call={call({ slug: 'p1', kind: 'review' }, '审单核对白板：1 单', 'mcp__emerge_tools__render_board')}
      />,
    )
    expect(screen.getByTestId('review-board-card')).toBeTruthy()
  })

  it("kind='audit' falls through to the generic tool card (render_audit_board never had one)", () => {
    render(
      <HoistedToolCard
        call={call({ slug: 'p1', kind: 'audit' }, '1. ✓ 报价单甲方为环胜', 'mcp__emerge_tools__render_board')}
      />,
    )
    expect(screen.queryByTestId('review-board-card')).toBeNull()
    expect(screen.queryByTestId('audit-card')).toBeNull()
    expect(screen.queryByTestId('audit-score-card')).toBeNull()
    // The generic ToolCall row still renders, with the bare tool name.
    expect(screen.getByText('render_board')).toBeTruthy()
  })

  it('legacy transcript name render_review_board (pre-P4-Task-10) still renders ReviewBoardCard', () => {
    act(() => {
      useProjects.setState({ selectedSlug: 'p1' })
      useReviewBoard.setState({ byProject: { p1: REVIEW_BOARD_PAYLOAD } })
    })
    render(
      <HoistedToolCard
        call={call({ slug: 'p1' }, '审单核对白板：1 单', 'mcp__emerge_tools__render_review_board')}
      />,
    )
    expect(screen.getByTestId('review-board-card')).toBeTruthy()
  })

  it('legacy transcript name render_audit_board (pre-P4-Task-10) still falls through to the generic tool card', () => {
    render(
      <HoistedToolCard
        call={call({ slug: 'p1' }, '1. ✓ 报价单甲方为环胜', 'mcp__emerge_tools__render_audit_board')}
      />,
    )
    expect(screen.queryByTestId('review-board-card')).toBeNull()
    expect(screen.getByText('render_audit_board')).toBeTruthy()
  })
})
