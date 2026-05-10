import { useState } from 'react'
import Shell from './components/Shell/Shell'
import Topbar from './components/Shell/Topbar'
import FSSpine from './components/Spine/FSSpine'
import ChatPanel from './components/Chat/ChatPanel'
import ContextSurface from './components/Context/ContextSurface'
import ReviewOverlay from './components/ReviewMode/ReviewOverlay'
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
  const [leftPeek, setLeftPeek] = useState(false)
  const [rightPeek, setRightPeek] = useState(false)

  const inReview = !!activeDocId

  // In review mode, panels are hidden by default; peek toggles reveal them.
  // Outside review, the user-controlled hidden flags apply.
  const effectiveLeftHidden  = inReview ? !leftPeek  : leftHidden
  const effectiveRightHidden = inReview ? !rightPeek : rightHidden

  const onToggleLeft  = () => inReview ? setLeftPeek(v => !v)  : setLeftHidden(v => !v)
  const onToggleRight = () => inReview ? setRightPeek(v => !v) : setRightHidden(v => !v)

  const schemaVersion = 'v' + (project?.active_version_id ?? '0')
  const schemaState: 'draft' | 'frozen' = project?.active_version_id ? 'frozen' : 'draft'

  return (
    <>
      <Shell
        topbar={
          <Topbar
            projectName={project?.name ?? ''}
            schemaVersion={schemaVersion}
            schemaState={schemaState}
            watchingCount={docs.length}
            improveJob={undefined}
            leftHidden={effectiveLeftHidden}
            rightHidden={effectiveRightHidden}
            onToggleLeft={onToggleLeft}
            onToggleRight={onToggleRight}
          />
        }
        left={<FSSpine />}
        center={inReview
          ? <ReviewOverlay
              onBack={() => useReview.getState().close()}
              leftPeek={leftPeek}
              setLeftPeek={setLeftPeek}
              rightPeek={rightPeek}
              setRightPeek={setRightPeek}
            />
          : <ChatPanel />}
        right={<ContextSurface onClose={onToggleRight} />}
        leftHidden={effectiveLeftHidden}
        rightHidden={effectiveRightHidden}
      />
    </>
  )
}
