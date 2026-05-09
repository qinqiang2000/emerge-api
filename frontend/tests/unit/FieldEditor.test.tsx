import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import FieldEditor from '../../src/components/ReviewMode/FieldEditor'

const SCHEMA = [
  { name: 'invoice_number', type: 'string', description: 'invoice no' },
  { name: 'total_amount', type: 'number', description: 'total' },
]

/** Stateful test wrapper — emulates the real parent (review store)
 *  by holding values in state and feeding them back via the values prop. */
function Stateful({
  initial,
  onChange,
  saving = false,
  onSave = () => {},
}: {
  initial: Record<string, unknown>
  onChange?: (name: string, value: unknown) => void
  saving?: boolean
  onSave?: () => void
}) {
  const [values, setValues] = useState<Record<string, unknown>>(initial)
  return (
    <FieldEditor
      schema={SCHEMA as any}
      values={values}
      onChange={(name, value) => {
        setValues((s) => ({ ...s, [name]: value }))
        onChange?.(name, value)
      }}
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

  it('calls onChange with field name and accumulated value as user types', async () => {
    const onChange = vi.fn()
    render(<Stateful initial={{ invoice_number: '' }} onChange={onChange} />)
    const input = screen.getByLabelText(/invoice_number/)
    await userEvent.type(input, 'INV-42')
    // last call has the full accumulated value
    expect(onChange).toHaveBeenLastCalledWith('invoice_number', 'INV-42')
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
      values={{ doc_type: 'invoice' }}
      onChange={onChange} onSave={() => {}} saving={false}
    />)
    expect(screen.getByRole('button', { name: 'invoice' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'others' })).toBeInTheDocument()
  })

  it('clicking an enum chip emits onChange', () => {
    const onChange = vi.fn()
    render(<FieldEditor
      schema={[{ name: 'doc_type', type: 'string', description: 'd', enum: ['a', 'b'] }]}
      values={{ doc_type: 'a' }}
      onChange={onChange} onSave={() => {}} saving={false}
    />)
    fireEvent.click(screen.getByRole('button', { name: 'b' }))
    expect(onChange).toHaveBeenCalledWith('doc_type', 'b')
  })

  it('renders number stepper for type=number', () => {
    render(<FieldEditor
      schema={[{ name: 'amount', type: 'number', description: 'd' }]}
      values={{ amount: 100 }}
      onChange={vi.fn()} onSave={() => {}} saving={false}
    />)
    expect(screen.getByRole('button', { name: '-' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+' })).toBeInTheDocument()
  })

  it('renders toggle for type=boolean', () => {
    const onChange = vi.fn()
    render(<FieldEditor
      schema={[{ name: 'is_paid', type: 'boolean', description: 'd' }]}
      values={{ is_paid: false }}
      onChange={onChange} onSave={() => {}} saving={false}
    />)
    const toggle = screen.getByRole('switch', { name: /is_paid/i })
    expect(toggle).toBeInTheDocument()
    fireEvent.click(toggle)
    expect(onChange).toHaveBeenCalledWith('is_paid', true)
  })
})
