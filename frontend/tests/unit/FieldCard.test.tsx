import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import FieldCard from '../../src/components/QuickLook/FieldCard'
import type { SchemaField } from '../../src/stores/schema'

const F = (over: Partial<SchemaField>): SchemaField => ({
  name: 'x',
  type: 'string',
  description: 'desc',
  ...over,
} as SchemaField)

describe('FieldCard', () => {
  it('renders name, type, description', () => {
    render(<FieldCard field={F({ name: 'invoice_number', description: 'the id' })} />)
    expect(screen.getByText('invoice_number')).toBeInTheDocument()
    expect(screen.getByText('string')).toBeInTheDocument()
    expect(screen.getByText('the id')).toBeInTheDocument()
  })

  it('shows required pill only when required=true', () => {
    const { rerender } = render(<FieldCard field={F({ required: true })} />)
    expect(screen.getByText('REQUIRED')).toBeInTheDocument()
    rerender(<FieldCard field={F({ required: false })} />)
    expect(screen.queryByText('REQUIRED')).not.toBeInTheDocument()
  })

  it('renders (no description) placeholder when description is empty', () => {
    render(<FieldCard field={F({ description: '' })} />)
    expect(screen.getByText('(no description)')).toBeInTheDocument()
  })

  it('renders examples joined by comma, capped at 6', () => {
    render(<FieldCard field={F({ examples: ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'] })} />)
    expect(screen.getByText(/examples · a, b, c, d, e, f/)).toBeInTheDocument()
    expect(screen.getByText(/\+ 2 more/)).toBeInTheDocument()
  })

  it('renders enum list when present', () => {
    render(<FieldCard field={F({ enum: ['draft', 'published'] })} />)
    expect(screen.getByText('enum · draft, published')).toBeInTheDocument()
  })

  it('reserves notes-hint slot rendered as em-dash placeholder', () => {
    render(<FieldCard field={F({})} />)
    expect(screen.getByTestId('field-notes-hint').textContent).toBe('—')
  })

  it('array<object> children are collapsed by default and expand on click', () => {
    const f = F({
      name: 'line_items',
      type: 'array<object>',
      children: [F({ name: 'sku', description: 'sku id' })],
    })
    render(<FieldCard field={f} />)
    expect(screen.queryByText('sku')).not.toBeInTheDocument()
    expect(screen.getByText('children: 1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /expand line_items/i }))
    expect(screen.getByText('sku')).toBeInTheDocument()
  })

  it('children render recursively (no depth cap)', () => {
    const f = F({
      name: 'a',
      type: 'array<object>',
      children: [
        F({ name: 'b', type: 'array<object>', children: [F({ name: 'c' })] }),
      ],
    })
    render(<FieldCard field={f} defaultExpanded />)
    expect(screen.getByText('a')).toBeInTheDocument()
    expect(screen.getByText('b')).toBeInTheDocument()
    expect(screen.getByText('c')).toBeInTheDocument()
  })
})
