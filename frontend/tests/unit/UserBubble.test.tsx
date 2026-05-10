/**
 * Originally tested UserBubble (removed in M7 T3).
 * Now tests Turn, which replaced UserBubble as the user-message container.
 */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import Turn from '../../src/components/Chat/Turn'

describe('Turn (user)', () => {
  it('renders children', () => {
    render(
      <Turn who="you" ts="just now">
        <div className="msg user">提取这些发票核心信息</div>
      </Turn>
    )
    expect(screen.getByText('提取这些发票核心信息')).toBeInTheDocument()
  })

  it('shows "you" label for user turns', () => {
    render(
      <Turn who="you" ts="just now">
        <span>hi</span>
      </Turn>
    )
    expect(screen.getByText('you')).toBeInTheDocument()
  })

  it('shows "agent" label for agent turns', () => {
    render(
      <Turn who="agent" ts="just now">
        <span>hi</span>
      </Turn>
    )
    expect(screen.getByText('agent')).toBeInTheDocument()
  })

  it('agent .who span has "agent" class', () => {
    const { container } = render(
      <Turn who="agent" ts="just now">
        <span>hi</span>
      </Turn>
    )
    const whoEl = container.querySelector('.who')
    expect(whoEl?.className).toContain('agent')
  })

  it('user .who span does not have "agent" class', () => {
    const { container } = render(
      <Turn who="you" ts="just now">
        <span>hi</span>
      </Turn>
    )
    const whoEl = container.querySelector('.who')
    expect(whoEl?.className).not.toContain('agent')
  })
})
