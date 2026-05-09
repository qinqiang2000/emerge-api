// frontend/src/components/ProjectList/ProjectItem.tsx
import type { Project } from '../../types/project'
import ExportBundleButton from '../Publish/ExportBundleButton'

interface Props {
  project: Project
  selected: boolean
  onSelect: () => void
}

export default function ProjectItem({ project, selected, onSelect }: Props) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onSelect()
      }}
      className={
        'w-full text-left px-4 py-2 transition-colors flex items-center gap-2 ' +
        (selected ? 'bg-subtle text-fg-primary' : 'text-fg-secondary hover:bg-subtle')
      }
    >
      <span className="font-mono text-sm truncate">{project.name}</span>
      {project.active_version_id && (
        <span className="text-xs text-accent-primary shrink-0">▲{project.active_version_id}</span>
      )}
      <span
        className="ml-auto shrink-0"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <ExportBundleButton
          projectId={project.project_id}
          activeVersionId={project.active_version_id}
        />
      </span>
    </div>
  )
}
