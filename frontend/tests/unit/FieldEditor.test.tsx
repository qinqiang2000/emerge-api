// tests/unit/FieldEditor.test.tsx
// Updated for T11 new DOM structure (contentEditable FieldRow, Section, ObjectField, ArrayField).
// Old M5 tests replaced with integration smoke tests per T11.10 spec.

import { useState } from 'react'
import { beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import FieldEditor from '../../src/components/ReviewMode/FieldEditor'
import { useReview } from '../../src/stores/review'

// FieldEditor reads activeField + activeEntityIdx from the review store now;
// reset between tests so state from one block doesn't leak into the next.
beforeEach(() => {
  useReview.setState({ activeField: null, activeEntityIdx: 0 })
})

const SCHEMA = [
  { name: 'invoice_number', type: 'string', description: 'invoice no' },
  { name: 'total_amount', type: 'string', description: 'total' },
]

/** Stateful test wrapper — emulates the real parent (review store). */
function Stateful({
  initial,
  schema = SCHEMA,
  onChange,
}: {
  initial: Record<string, unknown>
  schema?: typeof SCHEMA
  onChange?: (entityIdx: number, name: string, value: unknown) => void
}) {
  const [entities, setEntities] = useState<Record<string, unknown>[]>([initial])
  return (
    <FieldEditor
      schema={schema as any}
      entities={entities}
      onChange={(entityIdx, name, value) => {
        setEntities((s) => s.map((row, i) => i === entityIdx ? { ...row, [name]: value } : row))
        onChange?.(entityIdx, name, value)
      }}
      onAddEntity={() => setEntities((s) => [...s, {}])}
      onRemoveEntity={(idx) => setEntities((s) => s.filter((_, i) => i !== idx))}
    />
  )
}

// ── FieldEditor basic rendering ──────────────────────────────────────────────

describe('FieldEditor', () => {
  it('renders field names via FieldRow', () => {
    render(<Stateful initial={{ invoice_number: 'INV-1', total_amount: '99.5' }} />)
    // FieldRow renders field name in .name spans
    expect(screen.getByText('invoice_number')).toBeInTheDocument()
    expect(screen.getByText('total_amount')).toBeInTheDocument()
  })

  it('renders field values as contentEditable spans', () => {
    render(<Stateful initial={{ invoice_number: 'INV-1' }} />)
    // The .val contentEditable span should contain the value
    const valSpans = document.querySelectorAll('[contenteditable]')
    const found = Array.from(valSpans).some(el => el.textContent === 'INV-1')
    expect(found).toBe(true)
  })

  // Save button moved to ReviewBar in toolbar redesign; no footer save in FieldEditor.
})

// ── FieldRow cdot rendering ──────────────────────────────────────────────────

describe('FieldEditor FieldRow cdot', () => {
  it('renders a confidence dot for each field (default moss / high)', () => {
    render(<Stateful initial={{ invoice_number: 'INV-1', total_amount: '100' }} />)
    const dots = document.querySelectorAll('.cdot')
    // One cdot per field row (2 fields)
    expect(dots.length).toBeGreaterThanOrEqual(2)
  })
})

// ── Section toggle ───────────────────────────────────────────────────────────

describe('FieldEditor Section', () => {
  it('renders a section header with label "fields"', () => {
    render(<Stateful initial={{ invoice_number: 'INV-1' }} />)
    // Section label is rendered as italic serif .lab span
    expect(screen.getByText('fields')).toBeInTheDocument()
  })

  it('field count chip shows correct count', () => {
    render(<Stateful initial={{ invoice_number: 'INV-1', total_amount: '99' }} />)
    expect(screen.getByText('2 fields')).toBeInTheDocument()
  })

  it('clicking section header toggles body (collapses)', () => {
    render(<Stateful initial={{ invoice_number: 'INV-1' }} />)
    const sectHeader = document.querySelector('.sect-h')!
    expect(sectHeader).toBeInTheDocument()
    // Initially open — field names visible
    expect(screen.getByText('invoice_number')).toBeInTheDocument()
    fireEvent.click(sectHeader)
    // After collapse — field name spans should be gone
    expect(screen.queryByText('invoice_number')).not.toBeInTheDocument()
  })
})

// ── Active field ─────────────────────────────────────────────────────────────

describe('FieldEditor active field', () => {
  it('clicking a FieldRow adds .active class', () => {
    render(<Stateful initial={{ invoice_number: 'INV-1' }} />)
    const row = document.querySelector('.rev-fld')!
    expect(row).toBeInTheDocument()
    expect(row.classList.contains('active')).toBe(false)
    fireEvent.click(row)
    expect(row.classList.contains('active')).toBe(true)
  })

  it('clicking active row again deactivates it', () => {
    render(<Stateful initial={{ invoice_number: 'INV-1' }} />)
    const row = document.querySelector('.rev-fld')!
    fireEvent.click(row)
    expect(row.classList.contains('active')).toBe(true)
    fireEvent.click(row)
    expect(row.classList.contains('active')).toBe(false)
  })
})

// ── ObjectField ──────────────────────────────────────────────────────────────

describe('FieldEditor ObjectField', () => {
  it('renders ObjectField for type=object fields', () => {
    render(<FieldEditor
      schema={[{ name: 'address', type: 'object', description: '' }]}
      entities={[{ address: { street: '1 Main St', city: 'Anytown' } }]}
      onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
    />)
    // ObjectField header contains the field name and "object" type tag
    expect(screen.getByText('address')).toBeInTheDocument()
    expect(screen.getByText(/object · 2 keys/)).toBeInTheDocument()
  })

  it('ObjectField expands on header click to show JSON body', () => {
    render(<FieldEditor
      schema={[{ name: 'meta', type: 'object', description: '' }]}
      entities={[{ meta: { k: 'v' } }]}
      onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
    />)
    const objHead = document.querySelector('.objhead')!
    // Initially collapsed
    expect(document.querySelector('.objbody')).not.toBeInTheDocument()
    fireEvent.click(objHead)
    expect(document.querySelector('.objbody')).toBeInTheDocument()
    // JSON content visible
    expect(document.querySelector('.objbody')!.textContent).toContain('"k"')
  })

  it('ObjectField collapses again on second click', () => {
    render(<FieldEditor
      schema={[{ name: 'meta', type: 'object', description: '' }]}
      entities={[{ meta: { k: 'v' } }]}
      onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
    />)
    const objHead = document.querySelector('.objhead')!
    fireEvent.click(objHead)
    expect(document.querySelector('.objbody')).toBeInTheDocument()
    fireEvent.click(objHead)
    expect(document.querySelector('.objbody')).not.toBeInTheDocument()
  })
})

// ── ArrayField ───────────────────────────────────────────────────────────────

describe('FieldEditor ArrayField', () => {
  it('renders ArrayField for type=array fields', () => {
    render(<FieldEditor
      schema={[{ name: 'items', type: 'array', description: '' }]}
      entities={[{ items: [{ name: 'Widget', price: 10 }, { name: 'Gadget', price: 20 }] }]}
      onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
    />)
    expect(screen.getByText('items')).toBeInTheDocument()
    expect(screen.getByText(/array · 2 rows/)).toBeInTheDocument()
  })

  it('ArrayField shows row cards with index labels', () => {
    render(<FieldEditor
      schema={[{ name: 'lines', type: 'array', description: '' }]}
      entities={[{ lines: ['a', 'b'] }]}
      onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
    />)
    // Starts open by default — .rhead rows visible
    expect(screen.getByText('#1')).toBeInTheDocument()
    expect(screen.getByText('#2')).toBeInTheDocument()
  })

  it('clicking ArrayField header collapses the list', () => {
    render(<FieldEditor
      schema={[{ name: 'lines', type: 'array', description: '' }]}
      entities={[{ lines: ['a', 'b'] }]}
      onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
    />)
    const arrHead = document.querySelector('.arrhead')!
    fireEvent.click(arrHead)
    expect(document.querySelector('.arrlist')).not.toBeInTheDocument()
  })

  it('+ row button adds an empty entry', () => {
    const onChange = vi.fn()
    render(<FieldEditor
      schema={[{ name: 'lines', type: 'array', description: '' }]}
      entities={[{ lines: ['a'] }]}
      onChange={onChange} onAddEntity={() => {}} onRemoveEntity={() => {}}
    />)
    fireEvent.click(screen.getByRole('button', { name: 'add row' }))
    expect(onChange).toHaveBeenCalledWith(0, 'lines', ['a', {}])
  })

  it('delete row button removes the entry', () => {
    const onChange = vi.fn()
    render(<FieldEditor
      schema={[{ name: 'lines', type: 'array', description: '' }]}
      entities={[{ lines: ['a', 'b'] }]}
      onChange={onChange} onAddEntity={() => {}} onRemoveEntity={() => {}}
    />)
    // Click delete for row #1
    fireEvent.click(screen.getByRole('button', { name: 'delete row 1' }))
    expect(onChange).toHaveBeenCalledWith(0, 'lines', ['b'])
  })
})

// ── Multi-entity nav ─────────────────────────────────────────────────────────

describe('FieldEditor multi-entity', () => {
  it('shows entity nav strip when multiple entities', () => {
    render(<FieldEditor schema={[{ name: 'a', type: 'string', description: '' }]}
      entities={[{ a: 'x' }, { a: 'y' }]}
      onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
      />)
    expect(screen.getByText(/entity 1 of 2/)).toBeInTheDocument()
    expect(screen.getByLabelText('previous entity')).toBeInTheDocument()
    expect(screen.getByLabelText('next entity')).toBeInTheDocument()
  })

  it('add entity button is always present', () => {
    render(<FieldEditor schema={[{ name: 'a', type: 'string', description: '' }]}
      entities={[{ a: 'x' }]}
      onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
      />)
    expect(screen.getByLabelText('add entity')).toBeInTheDocument()
  })

  it('calls onAddEntity when + entity is clicked', () => {
    const onAdd = vi.fn()
    render(<FieldEditor schema={[{ name: 'a', type: 'string', description: '' }]}
      entities={[{ a: 'x' }]}
      onChange={() => {}} onAddEntity={onAdd} onRemoveEntity={() => {}}
      />)
    fireEvent.click(screen.getByLabelText('add entity'))
    expect(onAdd).toHaveBeenCalled()
  })
})

// ── Evidence badges (M5 click-to-page preserved) ─────────────────────────────

describe('FieldEditor evidence badges', () => {
  it('clicking an evidence badge jumps to that page', async () => {
    const jump = vi.fn()
    render(<FieldEditor schema={[{ name: 'a', type: 'string', description: '' }]}
      entities={[{ a: 'x' }]}
      evidence={[{ a: 3 }]}
      onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
      onJumpToPage={jump}
      />)
    await userEvent.click(screen.getByLabelText('jump to page 3'))
    expect(jump).toHaveBeenCalledWith(3)
  })
})

// ── JSON view ────────────────────────────────────────────────────────────────

describe('FieldEditor JSON view', () => {
  it('renders JSON view when view=json', () => {
    render(<FieldEditor
      schema={[{ name: 'a', type: 'string', description: '' }]}
      entities={[{ a: 'hello' }]}
      onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
     
      view="json"
    />)
    // .rev-json container should be present
    expect(document.querySelector('.rev-json')).toBeInTheDocument()
    // Key should be colored as .jk
    expect(document.querySelector('.jk')).toBeInTheDocument()
  })

  it('line numbers are rendered', () => {
    render(<FieldEditor
      schema={[{ name: 'total', type: 'string', description: '' }]}
      entities={[{ total: '100' }]}
      onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
     
      view="json"
    />)
    // Line numbers are in .ln spans
    const lnSpans = document.querySelectorAll('.ln')
    expect(lnSpans.length).toBeGreaterThan(0)
  })
})
