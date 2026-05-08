// frontend/src/components/DocPreview/DocPreview.tsx
export default function DocPreview() {
  return (
    <div className="flex flex-col h-full">
      <header className="px-4 py-3 font-heading text-sm uppercase tracking-wide text-fg-muted">
        Preview
      </header>
      <div className="flex-1 grid place-items-center text-fg-muted text-sm font-body">
        select a doc from chat to preview here
      </div>
    </div>
  )
}
