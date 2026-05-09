// frontend/src/components/ReviewMode/ReviewMode.tsx
import { useEffect } from 'react'
import { ChevronLeft } from 'lucide-react'

import { useReview } from '../../stores/review'
import { useDocs } from '../../stores/docs'
import { useSchema } from '../../stores/schema'

import FieldEditor from './FieldEditor'
import PdfViewer from './PdfViewer'

export default function ReviewMode() {
  const { activeProjectId, activeDocId, fields, notes, setField, setNote, save, close, saving, err } = useReview()
  const { byProject } = useDocs()
  const schema = useSchema((s) => (activeProjectId ? s.byProject[activeProjectId] ?? [] : []))
  const loadSchema = useSchema((s) => s.load)

  useEffect(() => {
    if (!activeProjectId) return
    void loadSchema(activeProjectId)
  }, [activeProjectId, loadSchema])

  const filename = activeProjectId
    ? byProject[activeProjectId]?.find((d) => d.doc_id === activeDocId)?.filename
    : undefined

  return (
    <div className="flex flex-col h-full bg-canvas text-fg-primary">
      <header className="flex items-center gap-3 px-4 py-2 border-b border-subtle">
        <button
          onClick={close}
          className="p-1 hover:bg-subtle rounded inline-flex items-center gap-1 text-sm"
          aria-label="back"
        >
          <ChevronLeft size={16} /> back
        </button>
        <span className="font-heading text-sm uppercase tracking-wide text-fg-muted">
          Review
        </span>
        <span className="font-mono text-sm">{filename ?? activeDocId}</span>
      </header>
      {err && (
        <div className="bg-subtle border-l-2 border-accent-danger px-4 py-2 text-sm">
          <span className="font-mono text-accent-danger">error</span>: {err}
        </div>
      )}
      <div className="flex-1 grid grid-cols-[60%_40%] min-h-0">
        <section className="border-r border-subtle min-h-0">
          <PdfViewer />
        </section>
        <section className="min-h-0">
          <FieldEditor
            schema={schema}
            values={fields}
            notes={notes}
            onChange={setField}
            onSetNote={setNote}
            onSave={save}
            saving={saving}
          />
        </section>
      </div>
    </div>
  )
}
