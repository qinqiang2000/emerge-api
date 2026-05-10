import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import ToolCall from '../../src/components/Chat/ToolCall'
import ToolRow from '../../src/components/Chat/ToolRow'

describe('ToolCall', () => {
  it('renders name and status chip', () => {
    render(<ToolCall name="freeze_version" status="done" />)
    expect(screen.getByText('freeze_version')).toBeInTheDocument()
    const root = screen.getByText('freeze_version').closest('[data-status]')
    expect(root?.getAttribute('data-status')).toBe('done')
  })

  it('renders args next to name', () => {
    render(<ToolCall name="derive_schema" args="3 fields" status="done" />)
    expect(screen.getByText('(3 fields)')).toBeInTheDocument()
  })

  it('starts closed; click opens and shows children', () => {
    render(
      <ToolCall name="read_schema" status="done">
        <ToolRow label="field-a" />
      </ToolCall>
    )
    expect(screen.queryByText('field-a')).toBeNull()
    const head = screen.getByRole('button')
    fireEvent.click(head)
    expect(screen.getByText('field-a')).toBeInTheDocument()
  })

  it('defaultOpen renders children immediately', () => {
    render(
      <ToolCall name="list_docs" status="done" defaultOpen>
        <ToolRow label="doc-1" />
      </ToolCall>
    )
    expect(screen.getByText('doc-1')).toBeInTheDocument()
  })

  it('footer renders when open', () => {
    render(
      <ToolCall name="propose" status="cand" defaultOpen footer={<button>Accept</button>}>
        <span>body</span>
      </ToolCall>
    )
    expect(screen.getByText('Accept')).toBeInTheDocument()
  })

  it('footer hidden when closed', () => {
    render(
      <ToolCall name="propose" status="cand" footer={<button>Accept</button>}>
        <span>body</span>
      </ToolCall>
    )
    expect(screen.queryByText('Accept')).toBeNull()
  })

  it('run status shows spinner chip', () => {
    render(<ToolCall name="extract_batch" status="run" />)
    const chip = screen.getByRole('status')
    expect(chip).toBeInTheDocument()
  })

  it('err status chip has err class', () => {
    render(<ToolCall name="extract_one" status="err" />)
    const root = screen.getByText('extract_one').closest('[data-status]')
    expect(root?.getAttribute('data-status')).toBe('err')
    const chip = root?.querySelector('.t-status.err')
    expect(chip).not.toBeNull()
  })

  it('strips prefix and renders display name', () => {
    render(<ToolCall name="derive_schema" status="done" />)
    expect(screen.getByText('derive_schema')).toBeInTheDocument()
  })
})

describe('ToolRow', () => {
  it('renders glyph, label, value, mini', () => {
    render(
      <div className="tool">
        <div className="t-body">
          <ToolRow glyph="✓" label="status" value="ok" mini="done" />
        </div>
      </div>
    )
    expect(screen.getByText('✓')).toBeInTheDocument()
    expect(screen.getByText('status')).toBeInTheDocument()
    expect(screen.getByText('ok')).toBeInTheDocument()
    expect(screen.getByText('done')).toBeInTheDocument()
  })

  it('defaults glyph to ·', () => {
    render(
      <div className="tool">
        <div className="t-body">
          <ToolRow label="x" />
        </div>
      </div>
    )
    expect(screen.getByText('·')).toBeInTheDocument()
  })
})
