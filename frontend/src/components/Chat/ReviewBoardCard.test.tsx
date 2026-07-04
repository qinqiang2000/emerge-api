// ReviewBoardCard — chat card for `render_review_board`. The tool's text return
// is narrative (not JSON), so the card self-pulls from the `useReviewBoard`
// store. Tests seed the store directly (no fetch — avoids jsdom's relative-URL
// undici trap) and assert the rendered doc list + open-board deep-link.
import { act, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { useProjects } from '../../stores/projects'
import { useReviewBoard } from '../../stores/reviewBoard'
import type { ReviewBoardPayload } from '../../lib/api'
import { firstSentence, ReviewBoardCardAdapter } from './ReviewBoardCard'
import type { ChatEvent } from '../../types/chat'

const PAYLOAD: ReviewBoardPayload = {
  docs: [
    { id: '2994530', verdict: 'fail', supplier: '安徽晶瑞药业有限公司', amount: '14107.5',
      invoice_no: '263420', memo: '发票云生成', reason: '维生素B1片数量不符，请备注换算关系。后续无关句。' },
    { id: '2981974', verdict: 'pass', supplier: '国药控股', amount: '2005.5',
      invoice_no: '261270', memo: '发票云生成', reason: '各商品组数量合计一致' },
  ],
  html_by_id: { '2994530': '<!doctype html><body>fail</body>', '2981974': '<!doctype html><body>pass</body>' },
  tally: { pass: 1, fail: 1, unclear: 0 },
  model_label: 'deepseek-v4-flash',
}

type ToolCallEvent = Extract<ChatEvent, { type: 'tool_call' }>

function call(overrides: Partial<ToolCallEvent> = {}): ToolCallEvent {
  return {
    type: 'tool_call',
    tool_name: 'mcp__emerge_tools__render_review_board',
    tool_input: { slug: 'p1' },
    tool_result: 'audit board text...',
    ok: true,
    ...overrides,
  } as ToolCallEvent
}

afterEach(() => {
  act(() => {
    useReviewBoard.setState({ byProject: {}, loading: {}, errors: {} })
    useProjects.setState({ selectedSlug: null })
  })
})

describe('firstSentence', () => {
  it('keeps only the first sentence at a CJK/ASCII terminator', () => {
    expect(firstSentence('维生素B1片数量不符，请备注。后续句。')).toBe('维生素B1片数量不符，请备注。')
    expect(firstSentence('one. two.')).toBe('one.')
  })
  it('truncates a long single sentence with an ellipsis', () => {
    const long = 'x'.repeat(80)
    const out = firstSentence(long)
    expect(out.endsWith('…')).toBe(true)
    expect(out.length).toBe(61)
  })
})

describe('ReviewBoardCardAdapter', () => {
  it('renders the doc list + tally when the board is cached and a project is selected', () => {
    act(() => {
      useProjects.setState({ selectedSlug: 'p1' })
      useReviewBoard.setState({ byProject: { p1: PAYLOAD } })
    })
    const { getByTestId } = render(<ReviewBoardCardAdapter call={call()} />)
    expect(getByTestId('review-board-card')).toBeTruthy()
    expect(getByTestId('review-board-open')).toBeTruthy()
    // Both docs render; reason shows only its first sentence.
    const card = getByTestId('review-board-card')
    expect(card.textContent).toContain('2994530')
    expect(card.textContent).toContain('2981974')
    expect(card.textContent).toContain('维生素B1片数量不符，请备注换算关系。')
    expect(card.textContent).not.toContain('后续无关句')
  })

  it('open button pushes ?reviewboard=1', () => {
    act(() => {
      useProjects.setState({ selectedSlug: 'p1' })
      useReviewBoard.setState({ byProject: { p1: PAYLOAD } })
    })
    const { getByTestId } = render(<ReviewBoardCardAdapter call={call()} />)
    act(() => { fireEvent.click(getByTestId('review-board-open')) })
    expect(window.location.search).toContain('reviewboard=1')
  })

  it('falls back to a plain ToolCall while running (no card)', () => {
    act(() => { useProjects.setState({ selectedSlug: 'p1' }) })
    const { queryByTestId } = render(
      <ReviewBoardCardAdapter call={call({ tool_result: null })} />,
    )
    expect(queryByTestId('review-board-card')).toBeNull()
  })

  it('falls back when no project is selected', () => {
    act(() => {
      useProjects.setState({ selectedSlug: null })
      useReviewBoard.setState({ byProject: { p1: PAYLOAD } })
    })
    const { queryByTestId } = render(<ReviewBoardCardAdapter call={call()} />)
    expect(queryByTestId('review-board-card')).toBeNull()
  })
})
