import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import ExportBundleButton from '../../src/components/Publish/ExportBundleButton'

describe('ExportBundleButton', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/')
  })

  it('does not render when active_version_id is null', () => {
    const { container } = render(<ExportBundleButton projectId="p_abc123def456" activeVersionId={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders when published', () => {
    render(<ExportBundleButton projectId="p_abc123def456" activeVersionId="v1" />)
    expect(screen.getByLabelText(/export/i)).toBeInTheDocument()
  })

  it('renders a same-origin export href', () => {
    render(<ExportBundleButton projectId="p_abc123def456" activeVersionId="v1" />)
    const link = screen.getByLabelText(/export/i)
    expect(link).toHaveAttribute('href', '/lab/projects/p_abc123def456/export')
  })
})
