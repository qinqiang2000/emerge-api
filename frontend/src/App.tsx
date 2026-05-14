import { useState, useEffect, useCallback } from 'react'
import Shell from './components/Shell/Shell'
import FSSpine from './components/Spine/FSSpine'
import ChatPanel from './components/Chat/ChatPanel'
import ContextSurface from './components/Context/ContextSurface'
import ReviewOverlay from './components/ReviewMode/ReviewOverlay'
import SchemaQuickLook from './components/QuickLook/SchemaQuickLook'
import PanelToggle from './components/Shell/PanelToggle'
import { useReview } from './stores/review'
import { useProjects } from './stores/projects'
import { useChat } from './stores/chat'

const KEY_LEFT_CHAT    = 'emerge.panel.leftHidden.chat'
const KEY_RIGHT_CHAT   = 'emerge.panel.rightHidden.chat'
const KEY_LEFT_REVIEW  = 'emerge.panel.leftHidden.review'
const KEY_RIGHT_REVIEW = 'emerge.panel.rightHidden.review'

const DEFAULTS = {
  [KEY_LEFT_CHAT]:    false,
  [KEY_RIGHT_CHAT]:   false,
  [KEY_LEFT_REVIEW]:  true,
  [KEY_RIGHT_REVIEW]: true,
}

function readBool(key: keyof typeof DEFAULTS): boolean {
  try {
    const v = localStorage.getItem(key)
    if (v === '1') return true
    if (v === '0') return false
  } catch { /* ignore */ }
  return DEFAULTS[key]
}

function writeBool(key: keyof typeof DEFAULTS, val: boolean) {
  try { localStorage.setItem(key, val ? '1' : '0') } catch { /* ignore */ }
}

export default function App() {
  const { activeFilename } = useReview()
  const { selectedId } = useProjects()

  const [leftHiddenChat,    setLeftHiddenChatState]    = useState<boolean>(() => readBool(KEY_LEFT_CHAT))
  const [rightHiddenChat,   setRightHiddenChatState]   = useState<boolean>(() => readBool(KEY_RIGHT_CHAT))
  const [leftHiddenReview,  setLeftHiddenReviewState]  = useState<boolean>(() => readBool(KEY_LEFT_REVIEW))
  const [rightHiddenReview, setRightHiddenReviewState] = useState<boolean>(() => readBool(KEY_RIGHT_REVIEW))

  const inReview = !!activeFilename

  const leftHidden  = inReview ? leftHiddenReview  : leftHiddenChat
  // Right rail: in chat mode with no project selected, the only payload
  // is metrics — which needs a project. Force-hide rather than show a
  // dead "select a project to see metrics" panel. Don't persist this; it
  // overrides the stored state only while !selectedId.
  const rightHiddenRaw = inReview ? rightHiddenReview : rightHiddenChat
  const rightHidden = !inReview && !selectedId ? true : rightHiddenRaw
  const rightToggleEnabled = !(!inReview && !selectedId)

  const onToggleLeft = useCallback(() => {
    if (inReview) {
      setLeftHiddenReviewState(v => { const next = !v; writeBool(KEY_LEFT_REVIEW, next); return next })
    } else {
      setLeftHiddenChatState(v => { const next = !v; writeBool(KEY_LEFT_CHAT, next); return next })
    }
  }, [inReview])

  const onToggleRight = useCallback(() => {
    if (inReview) {
      setRightHiddenReviewState(v => { const next = !v; writeBool(KEY_RIGHT_REVIEW, next); return next })
    } else {
      setRightHiddenChatState(v => { const next = !v; writeBool(KEY_RIGHT_CHAT, next); return next })
    }
  }, [inReview])

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
          ? <ReviewOverlay
              onBack={() => useReview.getState().close()}
              leftHidden={leftHidden}
              rightHidden={rightHidden}
              onToggleLeft={onToggleLeft}
              onToggleRight={onToggleRight}
            />
          : <ChatPanel />}
        leftHidden={leftHidden}
        rightHidden={rightHidden}
      />

      {/* Floating context panel — fixed overlay, visible when not hidden */}
      {!rightHidden && rightToggleEnabled && (
        <aside className="ctx">
          <ContextSurface onToggleRight={onToggleRight} />
        </aside>
      )}

      {/* Edge toggles: left shows in chat mode; right shows when panel hidden */}
      {!inReview && leftHidden && (
        <PanelToggle
          side="left"
          hidden={true}
          onClick={onToggleLeft}
          className="edge-toggle left"
        />
      )}
      {!inReview && rightHidden && rightToggleEnabled && (
        <PanelToggle
          side="right"
          hidden={true}
          onClick={onToggleRight}
          className="edge-toggle right"
        />
      )}
      <SchemaQuickLook />
    </>
  )
}
