// tests/unit/FieldRowAndArray.test.tsx
// Tests for Fix 1 (FieldRow .edited class) and Fix 2 (ArrayField duplicate row).

import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'

import FieldRow from '../../src/components/ReviewMode/FieldRow'
import FieldEditor from '../../src/components/ReviewMode/FieldEditor'

// ── FieldRow .edited highlighting ────────────────────────────────────────────

/**
 * FieldRow needs a stateful parent so onChange → re-render → isEdited recomputes.
 */
function FieldRowWrapper({
  initialValue,
  onChange,
}: {
  initialValue: string
  onChange?: (v: string) => void
}) {
  const [value, setValue] = useState<unknown>(initialValue)
  return (
    <FieldRow
      path="test_field"
      name="test_field"
      type="string"
      value={value}
      active={false}
      onChange={(v) => {
        setValue(v)
        onChange?.(v)
      }}
      onClick={() => {}}
    />
  )
}

describe('FieldRow .edited class', () => {
  it('does NOT have .edited class initially', () => {
    render(<FieldRowWrapper initialValue="hello" />)
    const val = document.querySelector('.val')!
    expect(val.classList.contains('edited')).toBe(false)
  })

  it('gains .edited class after blur with a different value', () => {
    render(<FieldRowWrapper initialValue="hello" />)
    const val = document.querySelector('[contenteditable]')! as HTMLElement
    // Simulate user editing the content
    val.textContent = 'world'
    fireEvent.blur(val)
    // After re-render, val span should have .edited
    const updatedVal = document.querySelector('.val')!
    expect(updatedVal.classList.contains('edited')).toBe(true)
  })

  it('loses .edited class when reverted to the original value', () => {
    render(<FieldRowWrapper initialValue="hello" />)
    const val = document.querySelector('[contenteditable]')! as HTMLElement

    // Change to something else
    val.textContent = 'world'
    fireEvent.blur(val)
    expect(document.querySelector('.val')!.classList.contains('edited')).toBe(true)

    // Revert to original
    val.textContent = 'hello'
    fireEvent.blur(val)
    expect(document.querySelector('.val')!.classList.contains('edited')).toBe(false)
  })
})

// ── ArrayField duplicate row ─────────────────────────────────────────────────

describe('ArrayField duplicate row', () => {
  it('duplicate button is rendered next to each row', () => {
    render(
      <FieldEditor
        schema={[{ name: 'lines', type: 'array', description: '' }]}
        entities={[{ lines: [{ name: 'Widget', price: 10 }] }]}
        onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
       
      />
    )
    expect(screen.getByRole('button', { name: 'duplicate row 1' })).toBeInTheDocument()
  })

  it('clicking duplicate appends a copy of the row immediately after the source', () => {
    const onChange = vi.fn()
    render(
      <FieldEditor
        schema={[{ name: 'lines', type: 'array', description: '' }]}
        entities={[{ lines: [{ name: 'Widget', price: 10 }, { name: 'Gadget', price: 20 }] }]}
        onChange={onChange} onAddEntity={() => {}} onRemoveEntity={() => {}}
       
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'duplicate row 1' }))
    expect(onChange).toHaveBeenCalledWith(
      0,
      'lines',
      [
        { name: 'Widget', price: 10 },
        { name: 'Widget', price: 10 }, // duplicate inserted at index 1
        { name: 'Gadget', price: 20 },
      ]
    )
  })

  it('duplicated row data matches the source row', () => {
    const onChange = vi.fn()
    render(
      <FieldEditor
        schema={[{ name: 'items', type: 'array', description: '' }]}
        entities={[{ items: [{ sku: 'A-1', qty: 3 }] }]}
        onChange={onChange} onAddEntity={() => {}} onRemoveEntity={() => {}}
       
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'duplicate row 1' }))
    const [, , newArray] = onChange.mock.calls[0]
    const arr = newArray as { sku: string; qty: number }[]
    expect(arr).toHaveLength(2)
    expect(arr[0]).toEqual({ sku: 'A-1', qty: 3 })
    expect(arr[1]).toEqual({ sku: 'A-1', qty: 3 })
    // Must be a distinct object (deep copy), not the same reference
    expect(arr[0]).not.toBe(arr[1])
  })
})
