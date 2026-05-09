import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import NotesPopover from '../../src/components/ReviewMode/NotesPopover'


describe('NotesPopover', () => {
  it('renders existing note text', () => {
    render(<NotesPopover fieldName="x" initial="hello" onSave={() => {}} onClose={() => {}} />)
    expect(screen.getByDisplayValue('hello')).toBeInTheDocument()
  })

  it('calls onSave with edited text', () => {
    const onSave = vi.fn()
    const onClose = vi.fn()
    render(<NotesPopover fieldName="x" initial="" onSave={onSave} onClose={onClose} />)
    const ta = screen.getByRole('textbox')
    fireEvent.change(ta, { target: { value: 'corrected note' } })
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    expect(onSave).toHaveBeenCalledWith('corrected note')
    expect(onClose).toHaveBeenCalled()
  })

  it('calls onClose without save on cancel', () => {
    const onSave = vi.fn()
    const onClose = vi.fn()
    render(<NotesPopover fieldName="x" initial="abc" onSave={onSave} onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onSave).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })
})
