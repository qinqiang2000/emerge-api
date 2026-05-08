// frontend/src/components/ProjectList/ProjectItem.tsx
import type { Project } from '../../types/project'

interface Props {
  project: Project
  selected: boolean
  onSelect: () => void
}

export default function ProjectItem({ project, selected, onSelect }: Props) {
  return (
    <button
      onClick={onSelect}
      className={
        'w-full text-left px-4 py-2 transition-colors ' +
        (selected ? 'bg-subtle text-fg-primary' : 'text-fg-secondary hover:bg-subtle')
      }
    >
      <span className="font-mono text-sm">{project.name}</span>
      {project.active_version_id && (
        <span className="ml-2 text-xs text-accent-primary">▲{project.active_version_id}</span>
      )}
    </button>
  )
}
