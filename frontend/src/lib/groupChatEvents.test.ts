// P4 Task 7 — score(kind=) folds score_audit/score_match into one tool name.
// `score` was already hoisted (kind='extract'); `run_audit`/legacy
// `score_audit` were already hoisted; `score_match` was NEVER hoisted — it
// always fell into the collapsed ToolStack. This pins that the merge did not
// silently change any of those three outcomes just because the Set can now
// only key on the single shared name `score`.
import { describe, expect, it } from 'vitest'

import type { ChatEvent } from '../types/chat'
import { groupChatEvents } from './groupChatEvents'

function toolCall(tool_name: string, tool_input: unknown): ChatEvent {
  return {
    type: 'tool_call',
    tool_use_id: 'tu_1',
    tool_name,
    tool_input,
    tool_result: '{}',
    ok: true,
  }
}

function isHoisted(tool_name: string, tool_input: unknown): boolean {
  const items = groupChatEvents([toolCall(tool_name, tool_input)])
  return items.length === 1 && items[0].kind === 'hoisted_tool'
}

const CALL = 'mcp__emerge_tools__'

describe('groupChatEvents — score(kind=) hoisting', () => {
  it('score with no kind (default extract) hoists, same as before the merge', () => {
    expect(isHoisted(`${CALL}score`, { slug: 'p_x' })).toBe(true)
  })

  it("score kind='extract' hoists", () => {
    expect(isHoisted(`${CALL}score`, { slug: 'p_x', kind: 'extract' })).toBe(true)
  })

  it("score kind='audit' hoists (score_audit was hoisted pre-merge)", () => {
    expect(isHoisted(`${CALL}score`, { slug: 'p_x', kind: 'audit' })).toBe(true)
  })

  it("score kind='match' does NOT hoist — score_match never hoisted pre-merge", () => {
    expect(isHoisted(`${CALL}score`, { slug: 'p_x', kind: 'match' })).toBe(false)
  })

  it('legacy transcript name score_audit still hoists', () => {
    expect(isHoisted(`${CALL}score_audit`, { slug: 'p_x' })).toBe(true)
  })

  it('legacy transcript name score_match still does not hoist', () => {
    expect(isHoisted(`${CALL}score_match`, { slug: 'p_x' })).toBe(false)
  })

  it('run_audit (unrelated to the score merge) still hoists', () => {
    expect(isHoisted(`${CALL}run_audit`, { slug: 'p_x' })).toBe(true)
  })

  it('an unrelated plumbing tool still collapses into the ToolStack', () => {
    expect(isHoisted(`${CALL}derive_schema`, { slug: 'p_x' })).toBe(false)
  })
})

// P4 Task 10 — render_board(kind=) folds render_audit_board/render_review_
// board into one tool name. render_review_board was ALWAYS hoisted (its
// ReviewBoardCard is the primary artifact); render_audit_board was NEVER
// hoisted (no card — legend text + page images only). This pins that the
// merge did not silently change either outcome now that the Set can only key
// on the single shared name `render_board`.
describe('groupChatEvents — render_board(kind=) hoisting', () => {
  it("render_board kind='review' hoists — render_review_board always did", () => {
    expect(isHoisted(`${CALL}render_board`, { slug: 'p_x', kind: 'review' })).toBe(true)
  })

  it("render_board kind='audit' does NOT hoist — render_audit_board never did", () => {
    expect(isHoisted(`${CALL}render_board`, { slug: 'p_x', kind: 'audit' })).toBe(false)
  })

  it('legacy transcript name render_review_board still hoists', () => {
    expect(isHoisted(`${CALL}render_review_board`, { slug: 'p_x' })).toBe(true)
  })

  it('legacy transcript name render_audit_board still does not hoist', () => {
    expect(isHoisted(`${CALL}render_audit_board`, { slug: 'p_x' })).toBe(false)
  })

  it('render_board with no kind (validation-error transcript) does not hoist', () => {
    expect(isHoisted(`${CALL}render_board`, { slug: 'p_x' })).toBe(false)
  })
})
