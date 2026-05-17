// frontend/src/components/ReviewMode/PreLabelNotice.tsx
//
// Banner shown in Review mode when the form is prefilled from a Pro-labeler
// pending draft (`reviewed/_pending/{filename}.json`) — i.e. `useReview.open()`
// found no human-verified `reviewed/` file but did find a pending draft.
//
// Saves to `reviewed/` automatically delete the matching pending file on the
// backend (inside the same `project_lock` as the reviewed write), so this
// banner disappears as soon as the boss clicks Save.

interface Props {
  labelerModel: string | null
}

export default function PreLabelNotice({ labelerModel }: Props) {
  return (
    <div
      style={{
        borderLeft: '2px solid var(--ochre)',
        padding: '8px 16px',
        fontFamily: 'var(--mono)',
        fontSize: 12,
        color: 'var(--ink-7)',
        background: 'var(--paper-1)',
      }}
      role="status"
    >
      Pro-labeled by {labelerModel ?? 'unknown'} · please verify and save
    </div>
  )
}
