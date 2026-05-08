import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import FieldEditor from '../../src/components/ReviewMode/FieldEditor'

const SCHEMA = [
  { name: 'invoice_number', type: 'string', description: 'invoice no' },
  { name: 'total_amount', type: 'number', description: 'total' },
]

describe('FieldEditor', () => {
  it('renders a labelled input per schema field', () => {
    render(
      <FieldEditor
        schema={SCHEMA as any}
        values={{ invoice_number: 'INV-1', total_amount: 99.5 }}
        onChange={() => {}}
        onSave={() => {}}
        saving={false}
      />,
    )
    expect(screen.getByLabelText(/invoice_number/)).toHaveValue('INV-1')
    expect(screen.getByLabelText(/total_amount/)).toHaveValue('99.5')
  })

  it('calls onChange with field name and new value when input changes', async () => {
    const onChange = vi.fn()
    render(
      <FieldEditor
        schema={SCHEMA as any}
        values={{ invoice_number: '' }}
        onChange={onChange}
        onSave={() => {}}
        saving={false}
      />,
    )
    const input = screen.getByLabelText(/invoice_number/)
    await userEvent.type(input, 'INV-42')
    // last call has the most-recent text typed (testing-library does keystrokes)
    expect(onChange).toHaveBeenCalledWith('invoice_number', 'INV-42')
  })

  it('disables save button when saving=true', () => {
    render(
      <FieldEditor
        schema={SCHEMA as any}
        values={{}}
        onChange={() => {}}
        onSave={() => {}}
        saving={true}
      />,
    )
    expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled()
  })
})
