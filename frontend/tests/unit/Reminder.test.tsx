import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { Reminder } from '../../src/components/Reminder'

describe('Reminder', () => {
  it.each(['note', 'tip', 'caution', 'warning'] as const)(
    'block form carries intent %s class + body content',
    (intent) => {
      const { container, getByText } = render(
        <Reminder intent={intent} title="t">body-text</Reminder>,
      )
      const root = container.firstChild as HTMLElement
      expect(root.classList.contains('rm')).toBe(true)
      expect(root.classList.contains(intent)).toBe(true)
      expect(getByText('t')).toBeInTheDocument()
      expect(getByText('body-text')).toBeInTheDocument()
    },
  )

  it.each(['note', 'tip', 'caution', 'warning'] as const)(
    'inline form carries intent %s class + body content',
    (intent) => {
      const { container, getByText } = render(
        <Reminder intent={intent} form="inline">saved</Reminder>,
      )
      const root = container.firstChild as HTMLElement
      expect(root.classList.contains('rm-inline')).toBe(true)
      expect(root.classList.contains(intent)).toBe(true)
      expect(getByText('saved')).toBeInTheDocument()
    },
  )

  it('block form omits title element when no title prop', () => {
    const { container } = render(<Reminder intent="note">x</Reminder>)
    expect(container.querySelector('.rm-title')).toBeNull()
  })
})
