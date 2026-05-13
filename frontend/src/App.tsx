import { useState, useEffect } from 'react'
import Shell from './components/Shell/Shell'
import Topbar from './components/Shell/Topbar'
import FSSpine from './components/Spine/FSSpine'
import ChatPanel from './components/Chat/ChatPanel'
import ContextSurface from './components/Context/ContextSurface'
import ReviewOverlay from './components/ReviewMode/ReviewOverlay'
import SchemaQuickLook from './components/QuickLook/SchemaQuickLook'
import { useReview } from './stores/review'
import { useProjects } from './stores/projects'
import { useDocs } from './stores/docs'
import { useChat } from './stores/chat'

export default function App() {
  const { activeDocId } = useReview()
  const { selectedId, projects } = useProjects()
  const project = projects.find(p => p.project_id === selectedId) ?? null
  const watchingCount = useDocs(s => (s.byProject[selectedId ?? ''] ?? []).length)

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

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey
      if (!mod) return
      // Cmd/Ctrl+Shift+O → new chat (use e.code for macOS Cmd+Shift invariance)
      if (e.shiftKey && e.code === 'KeyO' && selectedId) {
        e.preventDefault()
        useChat.getState().newChat(selectedId)
        return
      }
      // Cmd/Ctrl+. → toggle left sidebar
      if (!e.shiftKey && e.code === 'Period') {
        e.preventDefault()
        onToggleLeft()
        return
      }
      // Cmd/Ctrl+Shift+. → toggle right sidebar
      if (e.shiftKey && e.code === 'Period') {
        e.preventDefault()
        onToggleRight()
        return
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [selectedId, onToggleLeft, onToggleRight])

  const schemaVersion = project?.active_version_id ?? 'v0'
  const schemaState: 'draft' | 'frozen' = project?.active_version_id ? 'frozen' : 'draft'

  return (
    <>
      <Shell
        topbar={
          <Topbar
            projectName={project?.name ?? ''}
            schemaVersion={schemaVersion}
            schemaState={schemaState}
            watchingCount={watchingCount}
            improveJob={undefined}
            leftHidden={effectiveLeftHidden}
            rightHidden={effectiveRightHidden}
            onToggleLeft={onToggleLeft}
            onToggleRight={onToggleRight}
          />
        }
        left={<FSSpine />}
        center={inReview
          ? <ReviewOverlay onBack={() => useReview.getState().close()} />
          : <ChatPanel />}
        right={<ContextSurface />}
        leftHidden={effectiveLeftHidden}
        rightHidden={effectiveRightHidden}
      />
      <SchemaQuickLook />
    </>
  )
}
