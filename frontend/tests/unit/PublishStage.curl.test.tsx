// frontend/tests/unit/PublishStage.curl.test.tsx
//
// The published-id curl example (slug-transparency milestone): the public
// endpoint is now `POST /v1/extract` + a `published_id` form parameter, not
// `/v1/{project_id}/extract`. The KeyStage snippet must surface that shape so
// users can paste it straight into their production deploy.
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import PublishStage from '../../src/components/Publish/PublishStage'
import { sampleCurl } from '../../src/lib/api'

describe('sampleCurl (lib/api) — post-slug-transparency shape', () => {
  it('targets POST /v1/extract with a `published_id` form field', () => {
    const snippet = sampleCurl('pub_abc12345xyz0')
    expect(snippet).toContain('/v1/extract')
    expect(snippet).toMatch(/published_id=pub_abc12345xyz0/)
    expect(snippet).toContain('X-API-Key')
    // No more project-id-in-URL legacy shape.
    expect(snippet).not.toMatch(/\/v1\/[^/]+\/extract/)
    // EMERGE_API_KEY placeholder, never a real ek_ literal.
    expect(snippet).toContain('$EMERGE_API_KEY')
    expect(snippet).not.toMatch(/ek_[a-zA-Z0-9]{10,}/)
  })
})

describe('PublishStage KeyStage — published_id deploy hint', () => {
  it('renders the "sync to production" hint when publishedId is present', () => {
    render(
      <PublishStage
        stage="key"
        projectName="invoices"
        versionLabel="v1"
        keyPlaintext="ek_abcdefghijklmnopqrstuvwxyz0123"
        keyHash={'a'.repeat(64)}
        keyPrefix="ek_abcdefgh"
        createdAt="2026-05-14T00:00:00Z"
        sampleSnippet={sampleCurl('pub_deadbeef0001')}
        publishedId="pub_deadbeef0001"
        onClose={() => {}}
      />,
    )
    // The hint copy + the literal published_id are both surfaced.
    expect(screen.getByText(/Sync/)).toBeInTheDocument()
    expect(screen.getByText('pub_deadbeef0001')).toBeInTheDocument()
    expect(screen.getByText(/production deployment/)).toBeInTheDocument()
  })

  it('omits the hint when publishedId is null (nothing frozen yet)', () => {
    render(
      <PublishStage
        stage="key"
        projectName="invoices"
        versionLabel="v1"
        keyPlaintext="ek_abcdefghijklmnopqrstuvwxyz0123"
        keyHash={'a'.repeat(64)}
        keyPrefix="ek_abcdefgh"
        createdAt="2026-05-14T00:00:00Z"
        sampleSnippet={sampleCurl('pub_xxx')}
        publishedId={null}
        onClose={() => {}}
      />,
    )
    expect(screen.queryByText(/Sync/)).toBeNull()
  })

  it('curl snippet body in KeyStage contains /v1/extract + published_id', () => {
    const { container } = render(
      <PublishStage
        stage="key"
        projectName="invoices"
        versionLabel="v1"
        keyPlaintext="ek_abcdefghijklmnopqrstuvwxyz0123"
        keyHash={'a'.repeat(64)}
        keyPrefix="ek_abcdefgh"
        createdAt="2026-05-14T00:00:00Z"
        sampleSnippet={sampleCurl('pub_99887766aabb')}
        publishedId="pub_99887766aabb"
        onClose={() => {}}
      />,
    )
    const snip = container.querySelector('.pub-snip')
    expect(snip?.textContent).toContain('/v1/extract')
    expect(snip?.textContent).toMatch(/published_id=pub_99887766aabb/)
  })
})
