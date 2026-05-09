import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import UserBubble from '../../src/components/Chat/UserBubble'

describe('UserBubble', () => {
  it('renders the text content', () => {
    render(<UserBubble text="提取这些发票核心信息" />)
    expect(screen.getByText('提取这些发票核心信息')).toBeInTheDocument()
  })

  it('does not interpret markdown (plain text only)', () => {
    const { container } = render(<UserBubble text="**not bold**" />)
    expect(container.querySelector('strong')).toBeNull()
    expect(container.textContent).toContain('**not bold**')
  })

  it('outer container is right-aligned (justify-end)', () => {
    const { container } = render(<UserBubble text="hi" />)
    const outer = container.firstElementChild as HTMLElement
    expect(outer.className).toContain('justify-end')
  })

  it('bubble has bg-bubble-user', () => {
    const { container } = render(<UserBubble text="hi" />)
    const bubble = container.querySelector('[data-role="user-bubble"]')
    expect(bubble?.className).toContain('bg-bubble-user')
  })
})
