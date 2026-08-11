// frontend/src/components/ReviewMode/PaneLoading.tsx
//
// The one loading indicator both review panes use.
//
// Before this existed the two panes had wildly different loading vocabularies:
// the right pane printed a bare "加载中…" while the left silently kept the
// PREVIOUS doc's raster on screen. A reviewer stepping to the next doc saw the
// new doc's fields next to the old doc's page and had no way to tell — the
// panes didn't just look out of sync, they actively lied. One shared component
// means "this side hasn't arrived yet" always reads the same, whichever side
// is late.
type Props = {
  label: string
  /** Failure copy replaces the spinner with a still glyph — a pane that will
   *  never arrive must stop pretending to be on its way. */
  failed?: boolean
}

export default function PaneLoading({ label, failed }: Props) {
  return (
    <div className={'pane-loading' + (failed ? ' is-error' : '')} role="status">
      {failed ? (
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" aria-hidden="true">
          <circle cx="7" cy="7" r="5.5" />
          <line x1="4.6" y1="4.6" x2="9.4" y2="9.4" />
        </svg>
      ) : (
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" className="translate-spin" aria-hidden="true">
          <path d="M7 1.5 a5.5 5.5 0 1 1 -5.5 5.5" />
        </svg>
      )}
      <span>{label}</span>
    </div>
  )
}
