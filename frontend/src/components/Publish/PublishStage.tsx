import { useState } from 'react'
import { Check, Copy, KeyRound, X } from 'lucide-react'

import { useT } from '../../i18n'

// ─── Types ──────────────────────────────────────────────────────────────────

export interface CheckItem {
  key: string
  label: string
  ok: boolean
  detail?: string
}

type CheckProps = {
  stage: 'check'
  projectName: string
  checklist: CheckItem[]
  onAdvance: () => void
  onClose: () => void
}

type KeyProps = {
  stage: 'key'
  projectName: string
  versionLabel: string
  keyPlaintext: string
  keyHash: string
  keyPrefix: string
  createdAt: string
  sampleSnippet: string
  /** Latest frozen `pub_xxx`. When present, surface a "sync this to production"
   *  hint so users know the deploy-symmetry contract: emerge is staging,
   *  production replays the same `published_id`. Null = nothing frozen yet. */
  publishedId?: string | null
  onClose: () => void
}

export type PublishStageProps = CheckProps | KeyProps

// ─── Helpers ─────────────────────────────────────────────────────────────────

const READINESS_LABELS: Record<string, string> = {
  schema_non_empty: 'Schema non-empty',
  reviewed_and_f1: 'Reviewed & F1',
  reviewed_fields_in_schema: 'Reviewed fields in schema',
  no_running_jobs: 'No running jobs',
  contract_diff_compat: 'Contract diff compat',
}

function humanizeKey(key: string): string {
  return READINESS_LABELS[key]
    ?? key.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())
}

export function adaptReadiness(result: unknown): CheckItem[] | null {
  let obj: unknown = result
  if (typeof result === 'string') {
    try { obj = JSON.parse(result) } catch { return null }
  }
  if (!obj || typeof obj !== 'object') return null
  const checks = (obj as Record<string, unknown>).checks
  if (!Array.isArray(checks)) return null
  return checks.map((c: Record<string, unknown>) => ({
    key: String(c.key ?? c.label ?? '?'),
    label: c.label != null ? String(c.label) : humanizeKey(String(c.key ?? '?')),
    ok: c.status === 'pass',
    detail: c.detail != null ? String(c.detail) : undefined,
  }))
}

/** @deprecated use `sampleCurl` from `../../lib/api` — it builds the
 *  post-slug-transparency `POST /v1/extract` + `published_id` form. Kept here
 *  only so the existing PublishStage.test.tsx import compiles. */
export function sampleCurl(publishedIdOrLegacySlug: string): string {
  // Mirror the canonical helper in lib/api.ts. New code should import from
  // there; this re-export is back-compat for the test suite + any consumer
  // still passing the project-slug-shaped legacy arg.
  return `# call your new endpoint
curl https://api.emerge.run/v1/extract \\
  -H "X-API-Key: $EMERGE_API_KEY" \\
  -F "published_id=${publishedIdOrLegacySlug}" \\
  -F "file=@example.pdf"`
}

// ─── Copy button (M6 inline pattern) ─────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const t = useT()
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  return (
    <button
      type="button"
      aria-label={t('publish.copyApiKey')}
      title={copied ? t('publish.copied') : t('publish.copy')}
      onClick={handleCopy}
      className="pub-key-copy-btn"
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
      <span className="copy-label">{copied ? t('publish.copied') : t('publish.copy')}</span>
    </button>
  )
}

// ─── Stage: check ─────────────────────────────────────────────────────────────

function CheckStage({ projectName, checklist, onAdvance, onClose }: CheckProps) {
  const t = useT()
  const allOk = checklist.every(c => c.ok)

  return (
    <div className="pub-card">
      <div className="pub-eyebrow">
        {t('publish.eyebrow.readiness', { project: projectName })}
        <span className="ln" />
      </div>

      <h2 className="pub-h">
        {t('publish.headline.ready')} <em>{t('publish.headline.ready.em')}</em>
      </h2>

      <p className="pub-sub">{t('publish.sub.check')}</p>

      <div className="pub-checks">
        {checklist.map(item => (
          <div key={item.key} className={`pub-check ${item.ok ? 'ok' : 'warn'}`}>
            <span className="mk">{item.ok ? '✓' : '!'}</span>
            <span className="lab">{item.label}</span>
            {item.detail && <span className="det">{item.detail}</span>}
          </div>
        ))}
        {checklist.length === 0 && (
          <div className="pub-check ok">
            <span className="mk">✓</span>
            <span className="lab">{t('publish.checks.noRequired')}</span>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button
          type="button"
          onClick={onAdvance}
          className="pub-btn-primary"
          disabled={!allOk}
          title={allOk ? undefined : t('publish.fixWarnings')}
        >
          {t('publish.mint')}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="pub-btn-ghost"
        >
          {t('publish.cancel')}
        </button>
      </div>
    </div>
  )
}

// ─── Stage: key ───────────────────────────────────────────────────────────────

function KeyStage({ projectName, versionLabel, keyPlaintext, keyHash, keyPrefix, createdAt, sampleSnippet, publishedId, onClose }: KeyProps) {
  const t = useT()
  return (
    <div className="pub-card">
      <div className="pub-eyebrow">
        {t('publish.eyebrow.minted', { project: projectName, version: versionLabel })}
        <span className="ln" />
      </div>

      <h2 className="pub-h">
        {t('publish.headline.live')} <em>{t('publish.headline.live.em')}</em>
      </h2>

      <p className="pub-sub">{t('publish.sub.key')}</p>

      <div className="pub-key">
        <div className="lab2">
          <span>{t('publish.keyLabel', { project: projectName, version: versionLabel })}</span>
          <span className="warn">{t('publish.shownOnce', { prefix: keyPrefix, tail: keyHash.slice(-6) })}</span>
        </div>
        <div className="key">
          <KeyRound size={13} style={{ flexShrink: 0, opacity: 0.6 }} />
          <span style={{ flex: 1, wordBreak: 'break-all', letterSpacing: '.02em', fontSize: 13 }}>
            {keyPlaintext}
          </span>
          <CopyButton text={keyPlaintext} />
        </div>
        <div className="one">
          {t('publish.notShownAgain.before')}{' '}
          <strong>{keyPrefix}</strong> {t('publish.notShownAgain.after')}
          &nbsp;·&nbsp; {t('publish.created', { ts: createdAt })}
        </div>
      </div>

      <div className="pub-snip">
        <span className="c">{sampleSnippet.split('\n').map((line, i) => {
          // colour the comment line
          if (line.startsWith('#')) return <span key={i} className="c">{line}{'\n'}</span>
          // colour -H / -F flags
          const parts = line.split(/(\s+-[HF]\s)/g)
          return (
            <span key={i}>
              {parts.map((p, j) =>
                /^\s+-[HF]\s/.test(p)
                  ? <span key={j} className="k">{p}</span>
                  : p
              )}
              {'\n'}
            </span>
          )
        })}</span>
      </div>

      {publishedId && (
        <p className="pub-sub" style={{ marginTop: 8 }}>
          {t('publish.syncHint.before')} <code style={{ fontSize: '12px', background: 'var(--ink-soft)', padding: '0 4px' }}>{publishedId}</code> {t('publish.syncHint.after')}
        </p>
      )}

      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button
          type="button"
          aria-label={t('publish.saved.aria')}
          onClick={onClose}
          className="pub-btn-primary"
        >
          {t('publish.saved.button')}
        </button>
      </div>
    </div>
  )
}

// ─── PublishStage (main export) ───────────────────────────────────────────────

export default function PublishStage(props: PublishStageProps) {
  const t = useT()
  return (
    <div className="pub-stage inline" role={props.stage === 'check' ? 'region' : 'region'} aria-label={t('publish.title')}>
      <button
        type="button"
        aria-label={t('publish.close.aria')}
        onClick={props.onClose}
        style={{
          position: 'absolute',
          top: 12,
          right: 16,
          color: 'var(--ink-4)',
          background: 'none',
          border: 'none',
          cursor: 'default',
          display: 'flex',
          alignItems: 'center',
        }}
      >
        <X size={16} />
      </button>
      {props.stage === 'check'
        ? <CheckStage {...props} />
        : <KeyStage {...props} />}
    </div>
  )
}
