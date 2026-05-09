import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'

import ApiKeyRevealModal from '../../src/components/Publish/ApiKeyRevealModal'
import { useApiKey } from '../../src/stores/apiKey'


describe('ApiKeyRevealModal', () => {
  beforeEach(() => {
    useApiKey.setState({ current: null })
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    })
  })

  it('does not render when no payload is queued', () => {
    render(<ApiKeyRevealModal />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('renders when payload is set and shows copy + acknowledge controls', () => {
    useApiKey.setState({ current: {
      key_plaintext: 'ek_abcdefgh01234567890123456789ABCD',
      key_hash: 'a'.repeat(64),
      key_prefix: 'ek_abcdefgh',
      created_at: '2026-05-09T01:23:45Z',
      project_id: 'p_abc123def456',
      version_id: 'v1',
    }})
    render(<ApiKeyRevealModal />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/p_abc123def456/)).toBeInTheDocument()
    expect(screen.getByText(/v1/)).toBeInTheDocument()
    expect(screen.getByLabelText(/copy/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/我已保存/)).toBeInTheDocument()
  })

  it('copy button calls navigator.clipboard.writeText with plaintext', async () => {
    useApiKey.setState({ current: {
      key_plaintext: 'ek_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
      key_hash: 'b'.repeat(64),
      key_prefix: 'ek_xxxxxxxx',
      created_at: '2026-05-09T01:23:45Z',
      project_id: 'p_abc123def456',
      version_id: 'v1',
    }})
    render(<ApiKeyRevealModal />)
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/copy/i))
    })
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('ek_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
  })

  it('"我已保存" clears the payload from the store', () => {
    useApiKey.setState({ current: {
      key_plaintext: 'ek_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
      key_hash: 'c'.repeat(64),
      key_prefix: 'ek_xxxxxxxx',
      created_at: '2026-05-09T01:23:45Z',
      project_id: 'p_abc123def456',
      version_id: 'v1',
    }})
    render(<ApiKeyRevealModal />)
    fireEvent.click(screen.getByLabelText(/我已保存/))
    expect(useApiKey.getState().current).toBeNull()
  })
})
