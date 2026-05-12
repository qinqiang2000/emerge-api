import { useEffect } from 'react'

type HelpPopoverProps = {
  onClose: () => void
}

export default function HelpPopover({ onClose }: HelpPopoverProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    const onClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (!target.closest('.help-pop') && !target.closest('.help-btn')) onClose()
    }
    window.addEventListener('keydown', onKey)
    const t = setTimeout(() => window.addEventListener('mousedown', onClick), 0)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onClick)
      clearTimeout(t)
    }
  }, [onClose])

  return (
    <div className="help-pop" onClick={e => e.stopPropagation()}>
      <div className="ey">how this works</div>
      <h4>An agent that writes the API for you.</h4>
      <p>
        Drop documents into a folder. The agent reads them, derives a <code>prompt</code>,
        and runs first-pass extractions. You review the ones it's least sure about — every edit
        teaches it.
      </p>
      <div className="steps">
        <div className="step">
          <span className="n">1</span>
          <span className="t">drop PDFs into <code>docs/</code> · run <code>/init</code></span>
        </div>
        <div className="step">
          <span className="n">2</span>
          <span className="t">review the flagged docs · accept or correct</span>
        </div>
        <div className="step">
          <span className="n">3</span>
          <span className="t">run <code>/eval</code> · then <code>/improve</code> any weak fields</span>
        </div>
        <div className="step">
          <span className="n">4</span>
          <span className="t"><code>/publish</code> when you're ready · key is minted</span>
        </div>
      </div>
      <p style={{ color: 'var(--ink-3)', fontSize: 12.5, fontStyle: 'italic' }}>
        Type <code>/</code> in the composer for the full menu. Everything is on disk — you can
        always read or edit the files yourself.
      </p>
      <div className="closehint"><kbd>Esc</kbd> to close</div>
    </div>
  )
}
