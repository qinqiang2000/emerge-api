import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'

import AgentMessage from '../../src/components/Chat/AgentMessage'

describe('AgentMessage', () => {
  it('renders bold via markdown', () => {
    const { container } = render(<AgentMessage text="hello **world**" />)
    expect(container.querySelector('strong')?.textContent).toBe('world')
  })

  it('renders inline code', () => {
    const { container } = render(<AgentMessage text="use `read_schema`" />)
    expect(container.querySelector('code')?.textContent).toBe('read_schema')
  })

  it('renders fenced code block', () => {
    const { container } = render(<AgentMessage text={'```\nfoo()\n```'} />)
    expect(container.querySelector('pre code')?.textContent).toContain('foo()')
  })

  it('renders GFM tables', () => {
    const md = '| a | b |\n|---|---|\n| 1 | 2 |'
    const { container } = render(<AgentMessage text={md} />)
    expect(container.querySelectorAll('table thead th')).toHaveLength(2)
    expect(container.querySelectorAll('table tbody td')[0].textContent).toBe('1')
  })

  it('renders bullet lists', () => {
    const { container } = render(<AgentMessage text={'- a\n- b'} />)
    expect(container.querySelectorAll('ul li')).toHaveLength(2)
  })

  it('does NOT render raw HTML', () => {
    const text = 'safe <script>alert("x")</script> end'
    const { container } = render(<AgentMessage text={text} />)
    expect(container.querySelector('script')).toBeNull()
    expect(container.textContent).toContain('safe')
  })

  it('does NOT render external img tags from markdown', () => {
    const text = '![evil](http://evil.example.com/x.png)'
    const { container } = render(<AgentMessage text={text} />)
    expect(container.querySelector('img')).toBeNull()
  })

  it('still renders inline links but with rel=noreferrer noopener', () => {
    const { container } = render(<AgentMessage text="see [docs](https://example.com)" />)
    const a = container.querySelector('a')
    expect(a?.getAttribute('href')).toBe('https://example.com')
    expect(a?.getAttribute('rel')).toContain('noreferrer')
    expect(a?.getAttribute('target')).toBe('_blank')
  })
})
