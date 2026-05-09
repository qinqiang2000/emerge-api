import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import FieldEditor from '../../src/components/ReviewMode/FieldEditor'

const SCHEMA = [
  { name: 'invoice_number', type: 'string', description: 'invoice no' },
  { name: 'total_amount', type: 'number', description: 'total' },
]

/** Stateful test wrapper — emulates the real parent (review store)
 *  by holding entities in state and feeding them back via the entities prop. */
function Stateful({
  initial,
  onChange,
  saving = false,
  onSave = () => {},
}: {
  initial: Record<string, unknown>
  onChange?: (entityIdx: number, name: string, value: unknown) => void
  saving?: boolean
  onSave?: () => void
}) {
  const [entities, setEntities] = useState<Record<string, unknown>[]>([initial])
  return (
    <FieldEditor
      schema={SCHEMA as any}
      entities={entities}
      onChange={(entityIdx, name, value) => {
        setEntities((s) => s.map((row, i) => i === entityIdx ? { ...row, [name]: value } : row))
        onChange?.(entityIdx, name, value)
      }}
      onAddEntity={() => setEntities((s) => [...s, {}])}
      onRemoveEntity={(idx) => setEntities((s) => s.filter((_, i) => i !== idx))}
      onSave={onSave}
      saving={saving}
    />
  )
}

describe('FieldEditor', () => {
  it('renders a labelled input per schema field', () => {
    render(<Stateful initial={{ invoice_number: 'INV-1', total_amount: 99.5 }} />)
    expect(screen.getByLabelText(/invoice_number/)).toHaveValue('INV-1')
    expect(screen.getByLabelText(/total_amount/)).toHaveValue('99.5')
  })

  it('calls onChange with entity index, field name and accumulated value as user types', async () => {
    const onChange = vi.fn()
    render(<Stateful initial={{ invoice_number: '' }} onChange={onChange} />)
    const input = screen.getByLabelText(/invoice_number/)
    await userEvent.type(input, 'INV-42')
    // last call has entity index 0 + the full accumulated value
    expect(onChange).toHaveBeenLastCalledWith(0, 'invoice_number', 'INV-42')
  })

  it('disables save button when saving=true', () => {
    render(<Stateful initial={{}} saving={true} />)
    expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled()
  })
})

describe('FieldEditor type-derived controls', () => {
  it('renders enum chips for an enum string field', () => {
    const onChange = vi.fn()
    render(<FieldEditor
      schema={[{ name: 'doc_type', type: 'string', description: 'd', enum: ['invoice', 'others'] }]}
      entities={[{ doc_type: 'invoice' }]}
      onChange={onChange} onAddEntity={() => {}} onRemoveEntity={() => {}} onSave={() => {}} saving={false}
    />)
    expect(screen.getByRole('button', { name: 'invoice' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'others' })).toBeInTheDocument()
  })

  it('clicking an enum chip emits onChange', () => {
    const onChange = vi.fn()
    render(<FieldEditor
      schema={[{ name: 'doc_type', type: 'string', description: 'd', enum: ['a', 'b'] }]}
      entities={[{ doc_type: 'a' }]}
      onChange={onChange} onAddEntity={() => {}} onRemoveEntity={() => {}} onSave={() => {}} saving={false}
    />)
    fireEvent.click(screen.getByRole('button', { name: 'b' }))
    expect(onChange).toHaveBeenCalledWith(0, 'doc_type', 'b')
  })

  it('renders number stepper for type=number', () => {
    render(<FieldEditor
      schema={[{ name: 'amount', type: 'number', description: 'd' }]}
      entities={[{ amount: 100 }]}
      onChange={vi.fn()} onAddEntity={() => {}} onRemoveEntity={() => {}} onSave={() => {}} saving={false}
    />)
    expect(screen.getByRole('button', { name: '-' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+' })).toBeInTheDocument()
  })

  it('renders toggle for type=boolean', () => {
    const onChange = vi.fn()
    render(<FieldEditor
      schema={[{ name: 'is_paid', type: 'boolean', description: 'd' }]}
      entities={[{ is_paid: false }]}
      onChange={onChange} onAddEntity={() => {}} onRemoveEntity={() => {}} onSave={() => {}} saving={false}
    />)
    const toggle = screen.getByRole('switch', { name: /0-is_paid/i })
    expect(toggle).toBeInTheDocument()
    fireEvent.click(toggle)
    expect(onChange).toHaveBeenCalledWith(0, 'is_paid', true)
  })
})

describe('FieldEditor multi-entity', () => {
  it('renders one row per entity and add/remove buttons', () => {
    render(<FieldEditor schema={[{ name: 'a', type: 'string', description: '' }]}
      entities={[{ a: 'x' }, { a: 'y' }]}
      onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
      onSave={() => {}} saving={false} />)
    expect(screen.getAllByText(/entity #/).length).toBe(2)
    expect(screen.getByLabelText('add entity')).toBeInTheDocument()
    expect(screen.getAllByLabelText(/remove entity/).length).toBe(2)
  })
})

describe('FieldEditor evidence badges', () => {
  it('clicking a label with evidence page jumps to that page', async () => {
    const jump = vi.fn()
    render(<FieldEditor schema={[{ name: 'a', type: 'string', description: '' }]}
      entities={[{ a: 'x' }]}
      evidence={[{ a: 3 }]}
      onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
      onJumpToPage={jump}
      onSave={() => {}} saving={false} />)
    await userEvent.click(screen.getByLabelText('jump to page 3'))
    expect(jump).toHaveBeenCalledWith(3)
  })
})
