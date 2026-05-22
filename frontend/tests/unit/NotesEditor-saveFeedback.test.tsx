import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import NotesEditor from '../../src/components/QuickLook/NotesEditor'
import { useSchema } from '../../src/stores/schema'
import { usePrompts } from '../../src/stores/prompts'

const PID = 'p_notes'

function seedActivePrompt(notes = '') {
  usePrompts.setState({
    list: { [PID]: [] },
    activeByProject: {
      [PID]: {
        prompt_id: 'pr',
        label: 'Baseline',
        schema: [],
        global_notes: notes,
        derived_from: null,
        created_at: 'x',
        updated_at: 'x',
      } as any,
    },
    loading: {},
  })
}

describe('NotesEditor save feedback', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    seedActivePrompt('')
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('shows saving → saved → idle on successful blur, with saved held long enough to read', async () => {
    const saveActive = vi
      .spyOn(useSchema.getState(), 'saveActive')
      .mockResolvedValue(null)

    render(<NotesEditor slug={PID} value="" schema={[]} />)
    const ta = screen.getByPlaceholderText(/Overall instructions/i) as HTMLTextAreaElement

    // Edit + blur to trigger commit
    fireEvent.change(ta, { target: { value: 'hello' } })
    await act(async () => {
      fireEvent.blur(ta)
      // Drain the saveActive microtask. The pending state survives the
      // microtask boundary because we never advance timers — the saved hold
      // timer only fires after the explicit advance below.
      await Promise.resolve()
    })

    expect(saveActive).toHaveBeenCalledWith(PID, [], 'hello')
    expect(screen.getByText('saved')).toBeInTheDocument()
    // Critical: the saved pill must remain visible for a human-readable beat,
    // not flash by sub-second like the old `saving…` indicator.
    act(() => { vi.advanceTimersByTime(1499) })
    expect(screen.queryByText('saved')).toBeInTheDocument()
    act(() => { vi.advanceTimersByTime(2) })
    expect(screen.queryByText('saved')).not.toBeInTheDocument()
  })

  it('does not show saved pill on error; renders error block instead', async () => {
    vi.spyOn(useSchema.getState(), 'saveActive').mockResolvedValue({
      error_code: 'boom',
      error_message_en: 'something broke',
    })
    // Silence the console.error the component fires on save failure.
    vi.spyOn(console, 'error').mockImplementation(() => {})

    render(<NotesEditor slug={PID} value="" schema={[]} />)
    const ta = screen.getByPlaceholderText(/Overall instructions/i) as HTMLTextAreaElement
    fireEvent.change(ta, { target: { value: 'x' } })
    await act(async () => {
      fireEvent.blur(ta)
      await Promise.resolve()
    })

    expect(screen.queryByText('saved')).not.toBeInTheDocument()
    expect(screen.getByText('boom')).toBeInTheDocument()
    expect(screen.getByText('something broke')).toBeInTheDocument()
  })

  it('patches usePrompts.activeByProject in place after successful save (no cache nuke)', async () => {
    vi.spyOn(useSchema.getState(), 'saveActive').mockResolvedValue(null)
    seedActivePrompt('old')

    render(<NotesEditor slug={PID} value="old" schema={[]} />)
    const ta = screen.getByPlaceholderText(/Overall instructions/i) as HTMLTextAreaElement
    fireEvent.change(ta, { target: { value: 'new' } })
    await act(async () => {
      fireEvent.blur(ta)
      await Promise.resolve()
    })

    // list[PID] must NOT be deleted (regression guard against invalidate()
    // which would flash the spine to "(none yet)").
    expect(usePrompts.getState().list[PID]).toBeDefined()
    expect(usePrompts.getState().activeByProject[PID]?.global_notes).toBe('new')
  })
})
