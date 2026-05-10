import { useState } from 'react'
import Shell from './components/Shell/Shell'
import Topbar from './components/Shell/Topbar'
import ProjectList from './components/ProjectList/ProjectList'
import ChatPanel from './components/Chat/ChatPanel'
import DocList from './components/DocList/DocList'
import ReviewMode from './components/ReviewMode/ReviewMode'
import ApiKeyRevealModal from './components/Publish/ApiKeyRevealModal'
import { useReview } from './stores/review'
import { useProjects } from './stores/projects'
import { useDocs } from './stores/docs'

export default function App() {
  const { activeDocId } = useReview()
  const { selectedId, projects } = useProjects()
  const project = projects.find(p => p.project_id === selectedId) ?? null
  const docs = useDocs(s => s.byProject[selectedId ?? ''] ?? [])

  const [leftHidden, setLeftHidden] = useState(false)
  const [rightHidden, setRightHidden] = useState(false)

  const schemaVersion = 'v' + (project?.active_version_id ?? '0')
  const schemaState: 'draft' | 'frozen' = project?.active_version_id ? 'frozen' : 'draft'

  return (
    <>
      <ApiKeyRevealModal />
      <Shell
        topbar={
          <Topbar
            projectName={project?.name ?? ''}
            schemaVersion={schemaVersion}
            schemaState={schemaState}
            watchingCount={docs.length}
            improveJob={undefined}
            leftHidden={leftHidden}
            rightHidden={rightHidden}
            onToggleLeft={() => setLeftHidden(h => !h)}
            onToggleRight={() => setRightHidden(h => !h)}
          />
        }
        left={<ProjectList />}
        center={activeDocId ? <ReviewMode /> : <ChatPanel />}
        right={<DocList />}
        leftHidden={leftHidden}
        rightHidden={rightHidden}
      />
    </>
  )
}
