import { useEffect } from 'react'

import { useProjects } from '../../stores/projects'
import { useDocs } from '../../stores/docs'
import { useReview } from '../../stores/review'

import DocItem from './DocItem'

export default function DocList() {
  const { selectedId } = useProjects()
  const { byProject, refresh } = useDocs()
  const { open } = useReview()

  useEffect(() => {
    if (selectedId) void refresh(selectedId)
  }, [selectedId, refresh])

  return (
    <div className="flex flex-col h-full">
      <header className="px-4 py-3 font-heading text-sm uppercase tracking-wide text-fg-muted">
        Docs
      </header>
      {!selectedId && (
        <div className="flex-1 grid place-items-center text-fg-muted text-sm font-body">
          select a project to see its docs
        </div>
      )}
      {selectedId && (
        <ul className="flex-1 overflow-auto">
          {(byProject[selectedId] ?? []).map((d) => (
            <li key={d.doc_id}>
              <DocItem doc={d} onClick={(did) => open(selectedId, did)} />
            </li>
          ))}
          {(byProject[selectedId] ?? []).length === 0 && (
            <li className="px-4 py-3 text-fg-muted text-sm font-body">
              no docs yet — drop PDFs into the chat to upload
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
