import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'

import PublishStage, { adaptReadiness, sampleCurl } from '../../src/components/Publish/PublishStage'
import { useApiKey } from '../../src/stores/apiKey'

// ── fixtures ──────────────────────────────────────────────────────────────────

const checklist = [
  { key: 'schema', label: 'Schema frozen', ok: true },
  { key: 'docs',   label: 'Docs uploaded',  ok: true },
  { key: 'eval',   label: 'Eval score ≥ 0.8', ok: false, detail: 'score 0.72' },
]

const revealPayload = {
  key_plaintext: 'ek_abcdefghijklmnopqrstuvwxyz012345',
  key_hash: 'a'.repeat(64),
  key_prefix: 'ek_abcdefgh',
  created_at: '2026-05-10T00:00:00Z',
  project_id: 'invoices',
  version_id: 'v1',
}

// ── stage: check ──────────────────────────────────────────────────────────────

describe('PublishStage — check stage', () => {
  it('renders eyebrow with project name', () => {
    render(
      <PublishStage
        stage="check"
        projectName="invoices"
        checklist={checklist}
        onAdvance={vi.fn()}
        onClose={vi.fn()}
      />
    )
    expect(screen.getByText(/READINESS/i)).toBeInTheDocument()
    expect(screen.getByText(/invoices/)).toBeInTheDocument()
  })

  it('renders headline', () => {
    render(
      <PublishStage
        stage="check"
        projectName="invoices"
        checklist={checklist}
        onAdvance={vi.fn()}
        onClose={vi.fn()}
      />
    )
    expect(screen.getByText(/Ready to mint a/i)).toBeInTheDocument()
    expect(screen.getByText(/key\?/i)).toBeInTheDocument()
  })

  it('renders ok checks with ✓ mark', () => {
    render(
      <PublishStage
        stage="check"
        projectName="invoices"
        checklist={[{ key: 'k', label: 'Schema frozen', ok: true }]}
        onAdvance={vi.fn()}
        onClose={vi.fn()}
      />
    )
    const okEl = screen.getByText('Schema frozen').closest('.pub-check')
    expect(okEl).toHaveClass('ok')
    expect(okEl?.querySelector('.mk')?.textContent).toBe('✓')
  })

  it('renders warn checks with ! mark and detail', () => {
    render(
      <PublishStage
        stage="check"
        projectName="invoices"
        checklist={[{ key: 'e', label: 'Eval score', ok: false, detail: 'score 0.72' }]}
        onAdvance={vi.fn()}
        onClose={vi.fn()}
      />
    )
    const warnEl = screen.getByText('Eval score').closest('.pub-check')
    expect(warnEl).toHaveClass('warn')
    expect(warnEl?.querySelector('.mk')?.textContent).toBe('!')
    expect(screen.getByText('score 0.72')).toBeInTheDocument()
  })

  it('mint key button is disabled when any check fails', () => {
    render(
      <PublishStage
        stage="check"
        projectName="invoices"
        checklist={checklist}
        onAdvance={vi.fn()}
        onClose={vi.fn()}
      />
    )
    const mintBtn = screen.getByText(/mint key/i)
    expect(mintBtn).toBeDisabled()
  })

  it('mint key button is enabled when all checks pass', () => {
    const allOk = checklist.map(c => ({ ...c, ok: true }))
    render(
      <PublishStage
        stage="check"
        projectName="invoices"
        checklist={allOk}
        onAdvance={vi.fn()}
        onClose={vi.fn()}
      />
    )
    expect(screen.getByText(/mint key/i)).not.toBeDisabled()
  })

  it('clicking mint key → calls onAdvance', () => {
    const onAdvance = vi.fn()
    const allOk = checklist.map(c => ({ ...c, ok: true }))
    render(
      <PublishStage
        stage="check"
        projectName="invoices"
        checklist={allOk}
        onAdvance={onAdvance}
        onClose={vi.fn()}
      />
    )
    fireEvent.click(screen.getByText(/mint key/i))
    expect(onAdvance).toHaveBeenCalledOnce()
  })

  it('cancel calls onClose', () => {
    const onClose = vi.fn()
    render(
      <PublishStage
        stage="check"
        projectName="invoices"
        checklist={checklist}
        onAdvance={vi.fn()}
        onClose={onClose}
      />
    )
    fireEvent.click(screen.getByText(/cancel/i))
    expect(onClose).toHaveBeenCalledOnce()
  })
})

// ── stage: key ────────────────────────────────────────────────────────────────

describe('PublishStage — key stage', () => {
  beforeEach(() => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    })
  })

  it('renders KEY MINTED eyebrow with version label', () => {
    render(
      <PublishStage
        stage="key"
        projectName="invoices"
        versionLabel="v1"
        keyPlaintext={revealPayload.key_plaintext}
        keyHash={revealPayload.key_hash}
        keyPrefix={revealPayload.key_prefix}
        createdAt={revealPayload.created_at}
        sampleSnippet={sampleCurl('invoices')}
        onClose={vi.fn()}
      />
    )
    const eyebrow = document.querySelector('.pub-eyebrow')
    expect(eyebrow?.textContent).toMatch(/KEY MINTED/i)
    expect(eyebrow?.textContent).toContain('v1')
  })

  it('renders "Your API is live." headline', () => {
    render(
      <PublishStage
        stage="key"
        projectName="invoices"
        versionLabel="v1"
        keyPlaintext={revealPayload.key_plaintext}
        keyHash={revealPayload.key_hash}
        keyPrefix={revealPayload.key_prefix}
        createdAt={revealPayload.created_at}
        sampleSnippet={sampleCurl('invoices')}
        onClose={vi.fn()}
      />
    )
    expect(screen.getByText(/Your API is/i)).toBeInTheDocument()
    expect(screen.getByText(/live\./i)).toBeInTheDocument()
  })

  it('renders plaintext key from prop', () => {
    render(
      <PublishStage
        stage="key"
        projectName="invoices"
        versionLabel="v1"
        keyPlaintext={revealPayload.key_plaintext}
        keyHash={revealPayload.key_hash}
        keyPrefix={revealPayload.key_prefix}
        createdAt={revealPayload.created_at}
        sampleSnippet={sampleCurl('invoices')}
        onClose={vi.fn()}
      />
    )
    expect(screen.getByText(revealPayload.key_plaintext)).toBeInTheDocument()
  })

  it('copy button calls navigator.clipboard.writeText with plaintext key', async () => {
    render(
      <PublishStage
        stage="key"
        projectName="invoices"
        versionLabel="v1"
        keyPlaintext={revealPayload.key_plaintext}
        keyHash={revealPayload.key_hash}
        keyPrefix={revealPayload.key_prefix}
        createdAt={revealPayload.created_at}
        sampleSnippet={sampleCurl('invoices')}
        onClose={vi.fn()}
      />
    )
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/copy/i))
    })
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(revealPayload.key_plaintext)
  })

  it('close button calls onClose', () => {
    const onClose = vi.fn()
    render(
      <PublishStage
        stage="key"
        projectName="invoices"
        versionLabel="v1"
        keyPlaintext={revealPayload.key_plaintext}
        keyHash={revealPayload.key_hash}
        keyPrefix={revealPayload.key_prefix}
        createdAt={revealPayload.created_at}
        sampleSnippet={sampleCurl('invoices')}
        onClose={onClose}
      />
    )
    fireEvent.click(screen.getByText(/I've saved/i))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('snippet uses EMERGE_API_KEY placeholder, not the real key', () => {
    render(
      <PublishStage
        stage="key"
        projectName="invoices"
        versionLabel="v1"
        keyPlaintext={revealPayload.key_plaintext}
        keyHash={revealPayload.key_hash}
        keyPrefix={revealPayload.key_prefix}
        createdAt={revealPayload.created_at}
        sampleSnippet={sampleCurl('invoices')}
        onClose={vi.fn()}
      />
    )
    const snip = document.querySelector('.pub-snip')
    expect(snip?.textContent).toContain('$EMERGE_API_KEY')
    expect(snip?.textContent).not.toContain(revealPayload.key_plaintext)
  })
})

// ── adaptReadiness helper ─────────────────────────────────────────────────────

describe('adaptReadiness', () => {
  it('returns null for non-object input', () => {
    expect(adaptReadiness(null)).toBeNull()
    expect(adaptReadiness('string')).toBeNull()
    expect(adaptReadiness(42)).toBeNull()
  })

  it('returns null when checks is not an array', () => {
    expect(adaptReadiness({ checks: 'bad' })).toBeNull()
  })

  it('maps pass → ok=true, anything else → ok=false', () => {
    const result = adaptReadiness({
      checks: [
        { key: 'a', label: 'A', status: 'pass' },
        { key: 'b', label: 'B', status: 'fail' },
        { key: 'c', label: 'C', status: 'warn', detail: 'minor' },
      ],
    })
    expect(result).toEqual([
      { key: 'a', label: 'A', ok: true,  detail: undefined },
      { key: 'b', label: 'B', ok: false, detail: undefined },
      { key: 'c', label: 'C', ok: false, detail: 'minor' },
    ])
  })
})

// ── sampleCurl helper ─────────────────────────────────────────────────────────

describe('sampleCurl', () => {
  it('uses EMERGE_API_KEY placeholder', () => {
    const snippet = sampleCurl('invoices')
    expect(snippet).toContain('$EMERGE_API_KEY')
    expect(snippet).toContain('invoices')
    expect(snippet).not.toMatch(/ek_[a-zA-Z0-9]{10,}/)
  })
})

// ── apiKey store interaction ───────────────────────────────────────────────────

describe('useApiKey lifecycle', () => {
  beforeEach(() => {
    useApiKey.setState({ current: null })
  })

  it('setReveal stores payload and clear removes it', () => {
    useApiKey.getState().setReveal(revealPayload)
    expect(useApiKey.getState().current).toEqual(revealPayload)
    useApiKey.getState().clear()
    expect(useApiKey.getState().current).toBeNull()
  })
})
