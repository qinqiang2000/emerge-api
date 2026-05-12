import { render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { describe, expect, it, vi } from 'vitest'

import ChatErrorBoundary from '../../src/components/Chat/ChatErrorBoundary'

function Boom(): ReactElement {
  throw new Error('synthetic adapter crash')
}

describe('ChatErrorBoundary', () => {
  it('catches a child throw and renders an inline recovery message instead of unmounting the tree', () => {
    // Suppress React's expected error noise in this test only.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    render(
      <ChatErrorBoundary>
        <Boom />
      </ChatErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText(/Could not render this chat/i)).toBeInTheDocument()
    expect(screen.getByText('synthetic adapter crash')).toBeInTheDocument()
    spy.mockRestore()
  })

  it('renders children normally when no error', () => {
    render(<ChatErrorBoundary><div>thread ok</div></ChatErrorBoundary>)
    expect(screen.getByText('thread ok')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
