import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, fireEvent } from '@testing-library/react'
import SchemaFieldEditor from '../../src/components/QuickLook/SchemaFieldEditor'
import QuickLookHeader from '../../src/components/QuickLook/QuickLookHeader'
import { useSchema } from '../../src/stores/schema'
import type { QuickLookTarget } from '../../src/stores/quicklook'

const PID = 'p_field'
const FIELDS = [{ name: 'amount', type: 'string', description: 'total', required: false, enum: null, children: null }]

const TARGET: QuickLookTarget = { kind: 'prompt', pid: PID }

// Renders the QuickLook header (where the pill lives) above the editor (where
// the error banner lives). Matches the production composition in
// PromptQuickLook.
function Harness() {
  return (
    <>
      <QuickLookHeader
        target={TARGET}
        activeVersionId={null}
        maximized={false}
        onToggleMaximized={() => {}}
        onClose={() => {}}
      />
      <SchemaFieldEditor pid={PID} fields={FIELDS as any} />
    </>
  )
}

describe('SchemaFieldEditor save feedback (lifted to QuickLookHeader)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useSchema.setState({ byProject: { [PID]: FIELDS as any }, saveStatus: {}, saveError: {} })
  })

  afterEach(() => {
    vi.runAllTimers()
    vi.useRealTimers()
    vi.restoreAllMocks()
    useSchema.setState({ byProject: {}, saveStatus: {}, saveError: {} })
  })

  it('renders "fields" section label always', () => {
    render(<Harness />)
    const el = screen.getByText((content, node) =>
      node?.tagName !== 'BUTTON' && /fields/i.test(content) && !!node?.className?.includes('ql-fields-lab'),
    )
    expect(el).toBeInTheDocument()
  })

  it('shows saving → saved → idle in the header on checkbox toggle', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ schema: FIELDS }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )

    render(<Harness />)

    await act(async () => {
      fireEvent.click(screen.getByRole('checkbox'))
      // Yield several microtasks: setState (saving), fetch resolution, json
      // parse, finish (saved).
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(fetchSpy).toHaveBeenCalled()
    expect(screen.getByText('saved')).toBeInTheDocument()

    act(() => { vi.advanceTimersByTime(1499) })
    expect(screen.queryByText('saved')).toBeInTheDocument()
    act(() => { vi.advanceTimersByTime(2) })
    expect(screen.queryByText('saved')).not.toBeInTheDocument()
  })

  it('shows error banner in the editor (and no saved pill in header) on failed save', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: { error_code: 'schema_invalid', error_message_en: 'bad schema' } }), {
        status: 400, headers: { 'Content-Type': 'application/json' },
      }),
    )

    render(<Harness />)
    await act(async () => {
      fireEvent.click(screen.getByRole('checkbox'))
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(screen.queryByText('saved')).not.toBeInTheDocument()
    expect(screen.getByText('schema_invalid')).toBeInTheDocument()
  })

  it('renders fields label in empty state', () => {
    useSchema.setState({ byProject: {}, saveStatus: {}, saveError: {} })
    render(<SchemaFieldEditor pid={PID} fields={[]} />)
    expect(screen.getByText(/仅 notes 也能工作/i)).toBeInTheDocument()
    // Empty-state CTA was compacted from "+ add fields" to just "+" with
    // aria-label="add field"; the visible glyph lives in the title/aria-label now.
    expect(screen.getByRole('button', { name: /add field/i })).toBeInTheDocument()
  })
})
