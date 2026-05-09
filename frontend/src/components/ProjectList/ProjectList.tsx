// frontend/src/components/ProjectList/ProjectList.tsx
import { useEffect } from 'react'
import { Plus } from 'lucide-react'

import { useProjects } from '../../stores/projects'
import ProjectItem from './ProjectItem'

export default function ProjectList() {
  const { projects, refresh, select, selectedId } = useProjects()
  useEffect(() => { void refresh() }, [refresh])

  return (
    <div className="flex flex-col h-full">
      <header className="px-4 py-3 font-heading text-sm uppercase tracking-wide text-fg-muted">
        Projects
      </header>
      <ul className="flex-1 overflow-auto">
        {projects.map(p => (
          <li key={p.project_id}>
            <ProjectItem
              project={p}
              selected={p.project_id === selectedId}
              onSelect={() => select(p.project_id)}
            />
          </li>
        ))}
      </ul>
      <button
        onClick={() => select(null)}
        className="m-3 inline-flex items-center gap-2 text-sm text-fg-secondary hover:text-fg-primary"
      >
        <Plus size={14} /> new
      </button>
    </div>
  )
}
