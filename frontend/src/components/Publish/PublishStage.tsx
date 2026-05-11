import { useState } from 'react'
import { Check, Copy, KeyRound, X } from 'lucide-react'

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

export function sampleCurl(projectId: string): string {
  return `# call your new endpoint
curl https://api.emerge.run/v1/${projectId}/extract \\
  -H "Authorization: Bearer $EMERGE_API_KEY" \\
  -F file=@example.pdf`
}

// ─── Copy button (M6 inline pattern) ─────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
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
      aria-label="copy api key"
      title={copied ? 'Copied' : 'Copy'}
      onClick={handleCopy}
      className="pub-key-copy-btn"
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
      <span className="copy-label">{copied ? 'Copied' : 'Copy'}</span>
    </button>
  )
}

// ─── Stage: check ─────────────────────────────────────────────────────────────

function CheckStage({ projectName, checklist, onAdvance, onClose }: CheckProps) {
  const allOk = checklist.every(c => c.ok)

  return (
    <div className="pub-card">
      <div className="pub-eyebrow">
        READINESS · {projectName}
        <span className="ln" />
      </div>

      <h2 className="pub-h">
        Ready to mint a <em>key?</em>
      </h2>

      <p className="pub-sub">
        We ran a quick check against your project. Review the results below before
        issuing a new API key.
      </p>

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
            <span className="lab">no checks required</span>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button
          type="button"
          onClick={onAdvance}
          className="pub-btn-primary"
          disabled={!allOk}
          title={allOk ? undefined : 'Fix warnings before minting a key'}
        >
          mint key →
        </button>
        <button
          type="button"
          onClick={onClose}
          className="pub-btn-ghost"
        >
          cancel
        </button>
      </div>
    </div>
  )
}

// ─── Stage: key ───────────────────────────────────────────────────────────────

function KeyStage({ projectName, versionLabel, keyPlaintext, keyHash, keyPrefix, createdAt, sampleSnippet, onClose }: KeyProps) {
  return (
    <div className="pub-card">
      <div className="pub-eyebrow">
        KEY MINTED · {projectName}/{versionLabel}
        <span className="ln" />
      </div>

      <h2 className="pub-h">
        Your API is <em>live.</em>
      </h2>

      <p className="pub-sub">
        This is the only time this key will be shown. Copy it to a secure location
        before closing.
      </p>

      <div className="pub-key">
        <div className="lab2">
          <span>API key — {projectName} · {versionLabel}</span>
          <span className="warn">⚠ shown once · {keyPrefix}…{keyHash.slice(-6)}</span>
        </div>
        <div className="key">
          <KeyRound size={13} style={{ flexShrink: 0, opacity: 0.6 }} />
          <span style={{ flex: 1, wordBreak: 'break-all', letterSpacing: '.02em', fontSize: 13 }}>
            {keyPlaintext}
          </span>
          <CopyButton text={keyPlaintext} />
        </div>
        <div className="one">
          This key will not be shown again. After you close, only the prefix{' '}
          <strong>{keyPrefix}</strong> and a short hash will remain.
          &nbsp;·&nbsp; created {createdAt}
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

      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button
          type="button"
          aria-label="I've saved this key — close"
          onClick={onClose}
          className="pub-btn-primary"
        >
          I've saved this key — close
        </button>
      </div>
    </div>
  )
}

// ─── PublishStage (main export) ───────────────────────────────────────────────

export default function PublishStage(props: PublishStageProps) {
  return (
    <div className="pub-stage inline" role={props.stage === 'check' ? 'region' : 'region'} aria-label="Publish">
      <button
        type="button"
        aria-label="close publish panel"
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
