import { useState, useEffect } from 'react'
import Shell from './components/Shell/Shell'
import FSSpine from './components/Spine/FSSpine'
import ChatPanel from './components/Chat/ChatPanel'
import ContextSurface from './components/Context/ContextSurface'
import ReviewOverlay from './components/ReviewMode/ReviewOverlay'
import SchemaQuickLook from './components/QuickLook/SchemaQuickLook'
import { useReview } from './stores/review'
import { useProjects } from './stores/projects'
import { useChat } from './stores/chat'

function IconExpandLeft() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="2.5" y1="4" x2="13.5" y2="4"/>
      <line x1="2.5" y1="8" x2="13.5" y2="8"/>
      <line x1="2.5" y1="12" x2="13.5" y2="12"/>
    </svg>
  )
}

function IconExpandRight() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="12" height="10" rx="1.5"/>
      <line x1="9.5" y1="3.4" x2="9.5" y2="12.6"/>
    </svg>
  )
}

export default function App() {
  const { activeDocId } = useReview()
  const { selectedId } = useProjects()

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

  return (
    <>
      <Shell
        left={<FSSpine onToggleLeft={onToggleLeft} />}
        center={inReview
          ? <ReviewOverlay onBack={() => useReview.getState().close()} />
          : <ChatPanel />}
        right={<ContextSurface onToggleRight={onToggleRight} />}
        leftHidden={effectiveLeftHidden}
        rightHidden={effectiveRightHidden}
      />
      {effectiveLeftHidden && (
        <button
          type="button"
          className="edge-toggle left"
          onClick={onToggleLeft}
          title="Show projects (⌘.)"
          aria-label="Show projects"
        >
          <IconExpandLeft />
        </button>
      )}
      {effectiveRightHidden && (
        <button
          type="button"
          className="edge-toggle right"
          onClick={onToggleRight}
          title="Show context (⌘⇧.)"
          aria-label="Show context"
        >
          <IconExpandRight />
        </button>
      )}
      <SchemaQuickLook />
    </>
  )
}
