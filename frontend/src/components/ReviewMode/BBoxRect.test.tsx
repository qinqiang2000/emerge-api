import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { BBoxRect } from './BBoxRect'

describe('BBoxRect', () => {
  it('computes left/top/width/height as % of page dims', () => {
    const { container } = render(
      <BBoxRect bbox={[100, 200, 300, 250]} pageW={1000} pageH={2000} />,
    )
    const el = container.firstChild as HTMLElement
    // left = 100/1000 = 10%, top = 200/2000 = 10%
    expect(el.style.left).toBe('10%')
    expect(el.style.top).toBe('10%')
    // width = (300-100)/1000 = 20%, height = (250-200)/2000 = 2.5%
    expect(el.style.width).toBe('20%')
    expect(el.style.height).toBe('2.5%')
    expect(el.style.position).toBe('absolute')
  })

  it('defaults to a div but renders the requested element via `as`', () => {
    const { container: divC } = render(
      <BBoxRect bbox={[0, 0, 10, 10]} pageW={100} pageH={100} />,
    )
    expect((divC.firstChild as HTMLElement).tagName).toBe('DIV')

    const { container: spanC } = render(
      <BBoxRect as="span" bbox={[0, 0, 10, 10]} pageW={100} pageH={100} />,
    )
    expect((spanC.firstChild as HTMLElement).tagName).toBe('SPAN')
  })

  it('merges caller style on top of the computed positioning', () => {
    const { container } = render(
      <BBoxRect
        bbox={[0, 0, 50, 50]}
        pageW={100}
        pageH={100}
        style={{ fontSize: '12px', color: 'transparent' }}
      />,
    )
    const el = container.firstChild as HTMLElement
    expect(el.style.left).toBe('0%')
    expect(el.style.width).toBe('50%')
    expect(el.style.fontSize).toBe('12px')
    expect(el.style.color).toBe('transparent')
  })

  it('passes through arbitrary DOM props (className, data-*) and children', () => {
    const { container } = render(
      <BBoxRect
        bbox={[0, 0, 10, 10]}
        pageW={100}
        pageH={100}
        className="text-layer-span"
        data-span-index={3}
      >
        hello
      </BBoxRect>,
    )
    const el = container.firstChild as HTMLElement
    expect(el.className).toBe('text-layer-span')
    expect(el.getAttribute('data-span-index')).toBe('3')
    expect(el.textContent).toBe('hello')
  })
})
