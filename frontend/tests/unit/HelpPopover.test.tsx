import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import HelpPopover from '../../src/components/Shell/HelpPopover'
import Topbar from '../../src/components/Shell/Topbar'

describe('HelpPopover', () => {
  const noop = () => {}

  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('renders the eyebrow copy', () => {
    render(<HelpPopover onClose={noop} />)
    expect(screen.getByText('how this works')).toBeInTheDocument()
  })

  it('renders the headline copy', () => {
    render(<HelpPopover onClose={noop} />)
    expect(screen.getByRole('heading', { level: 4 })).toHaveTextContent(
      'An agent that writes the API for you.',
    )
  })

  it('renders all 4 steps', () => {
    render(<HelpPopover onClose={noop} />)
    const steps = document.querySelectorAll('.help-pop .step')
    expect(steps).toHaveLength(4)
    // step numbers
    const ns = document.querySelectorAll('.help-pop .step .n')
    expect(ns[0].textContent).toBe('1')
    expect(ns[1].textContent).toBe('2')
    expect(ns[2].textContent).toBe('3')
    expect(ns[3].textContent).toBe('4')
  })

  it('step 1 contains /init code', () => {
    render(<HelpPopover onClose={noop} />)
    const steps = document.querySelectorAll('.help-pop .step .t')
    expect(steps[0].textContent).toContain('/init')
  })

  it('step 4 contains /publish code', () => {
    render(<HelpPopover onClose={noop} />)
    const steps = document.querySelectorAll('.help-pop .step .t')
    expect(steps[3].textContent).toContain('/publish')
  })

  it('renders Esc close hint', () => {
    render(<HelpPopover onClose={noop} />)
    const kbd = document.querySelector('.help-pop .closehint kbd')
    expect(kbd).toBeTruthy()
    expect(kbd?.textContent).toBe('Esc')
  })

  it('calls onClose on Escape keydown', () => {
    const onClose = vi.fn()
    render(<HelpPopover onClose={onClose} />)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('does not call onClose on other keys', () => {
    const onClose = vi.fn()
    render(<HelpPopover onClose={onClose} />)
    fireEvent.keyDown(window, { key: 'Enter' })
    expect(onClose).not.toHaveBeenCalled()
  })

  it('calls onClose when clicking outside (not .help-pop or .help-btn)', () => {
    const onClose = vi.fn()
    render(<HelpPopover onClose={onClose} />)
    // Advance past the setTimeout(0) that defers mousedown listener registration
    act(() => { vi.runAllTimers() })
    const outside = document.createElement('div')
    document.body.appendChild(outside)
    fireEvent.mouseDown(outside)
    expect(onClose).toHaveBeenCalled()
    outside.remove()
  })

  it('does not call onClose when clicking inside .help-pop', () => {
    const onClose = vi.fn()
    render(<HelpPopover onClose={onClose} />)
    act(() => { vi.runAllTimers() })
    const pop = document.querySelector('.help-pop') as HTMLElement
    fireEvent.mouseDown(pop)
    expect(onClose).not.toHaveBeenCalled()
  })
})

describe('Topbar ? button', () => {
  const defaultProps = {
    projectName: 'test-proj',
    schemaVersion: 'v1',
    schemaState: 'draft' as const,
    watchingCount: 0,
    leftHidden: false,
    rightHidden: false,
    onToggleLeft: () => {},
    onToggleRight: () => {},
  }

  it('renders the ? help button', () => {
    render(<Topbar {...defaultProps} />)
    expect(screen.getByRole('button', { name: /how this works/i })).toBeInTheDocument()
  })

  it('popover is not shown initially', () => {
    render(<Topbar {...defaultProps} />)
    expect(document.querySelector('.help-pop')).toBeNull()
  })

  it('clicking ? opens the popover', () => {
    render(<Topbar {...defaultProps} />)
    const btn = screen.getByRole('button', { name: /how this works/i })
    fireEvent.click(btn)
    expect(document.querySelector('.help-pop')).toBeTruthy()
  })

  it('clicking ? again closes the popover', () => {
    render(<Topbar {...defaultProps} />)
    const btn = screen.getByRole('button', { name: /how this works/i })
    fireEvent.click(btn)
    fireEvent.click(btn)
    expect(document.querySelector('.help-pop')).toBeNull()
  })

  it('? button has .on class when popover is open', () => {
    render(<Topbar {...defaultProps} />)
    const btn = screen.getByRole('button', { name: /how this works/i })
    fireEvent.click(btn)
    expect(btn.classList.contains('on')).toBe(true)
  })
})
