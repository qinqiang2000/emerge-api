import { useState, useEffect, useCallback } from 'react'
import Shell from './components/Shell/Shell'
import FSSpine from './components/Spine/FSSpine'
import ChatPanel from './components/Chat/ChatPanel'
import ContextSurface from './components/Context/ContextSurface'
import ReviewOverlay from './components/ReviewMode/ReviewOverlay'
import PromptQuickLook from './components/QuickLook/PromptQuickLook'
import PanelToggle from './components/Shell/PanelToggle'
import { useReview } from './stores/review'
import { useProjects } from './stores/projects'
import { useChat } from './stores/chat'
import { pathForSlug, readSlugFromPathname } from './lib/slugUrl'

const KEY_LEFT_CHAT    = 'emerge.panel.leftHidden.chat'
const KEY_RIGHT_CHAT   = 'emerge.panel.rightHidden.chat'
const KEY_LEFT_REVIEW  = 'emerge.panel.leftHidden.review'
// In review mode this controls the review chat third column (PDF | Fields |
// ReviewChatColumn). It used to control ContextSurface visibility in review,
// but ContextSurface is never rendered while in review (the form needs the
// full chrome). Key name is preserved so existing user preferences carry over —
// `true` (the default) keeps the chat closed, matching the prior behavior of
// hiding the right rail on first entry.
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
  const { selectedSlug } = useProjects()

  // URL ↔ store sync.
  //
  // The frontend has no router despite the `react-router-dom` dep — slug
  // selection has always lived in the Zustand store, so the address bar was
  // decorative-only. Reloading `/p/foo` would drop selection back to `null`
  // and the composer would silently fall through to the `p_unset` empty-hero
  // path: the backend would mint a fresh project on every "send" instead of
  // honouring the URL. Linking and bookmarks were also dead.
  //
  // Three-way sync without pulling in a router:
  //   (a) on mount: read `/p/{slug}` and hydrate the store
  //   (b) on `selectedSlug` change: pushState (but skip the no-op write that
  //       would dirty history with the same path)
  //   (c) on browser back/forward (`popstate`): re-read the URL into the store
  useEffect(() => {
    const initial = readSlugFromPathname(window.location.pathname)
    if (initial) useProjects.getState().select(initial)
    const onPop = () => useProjects.getState().select(
      readSlugFromPathname(window.location.pathname),
    )
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  useEffect(() => {
    const target = pathForSlug(selectedSlug, window.location.search, window.location.hash)
    const current = window.location.pathname + window.location.search + window.location.hash
    if (target !== current) {
      window.history.pushState(null, '', target)
    }
  }, [selectedSlug])

  const [leftHiddenChat,    setLeftHiddenChatState]    = useState<boolean>(() => readBool(KEY_LEFT_CHAT))
  const [rightHiddenChat,   setRightHiddenChatState]   = useState<boolean>(() => readBool(KEY_RIGHT_CHAT))
  const [leftHiddenReview,  setLeftHiddenReviewState]  = useState<boolean>(() => readBool(KEY_LEFT_REVIEW))
  const [rightHiddenReview, setRightHiddenReviewState] = useState<boolean>(() => readBool(KEY_RIGHT_REVIEW))

  const inReview = !!activeFilename

  const leftHidden  = inReview ? leftHiddenReview  : leftHiddenChat
  // Right rail behavior:
  //   - chat mode  → controls the `ContextSurface` fixed overlay and Shell's
  //                  right-column spacer (so center doesn't slide under it).
  //                  Force-hidden when no project (metrics need a project).
  //   - review mode → controls the **review chat third column** *inside*
  //                  ReviewOverlay. ContextSurface is not rendered. Shell's
  //                  right-column spacer must collapse to 0 regardless, so the
  //                  review's 3-col layout can occupy the full center width.
  const rightHiddenChatEffective = !selectedSlug ? true : rightHiddenChat
  // For Shell: in review mode always collapse the spacer (no overlay lives
  // there). For the third column itself we still honor the review-scoped
  // hidden state — passed separately to ReviewOverlay.
  const shellRightHidden = inReview ? true : rightHiddenChatEffective
  const reviewChatHidden = rightHiddenReview
  const rightToggleEnabled = inReview || !!selectedSlug

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
      if (e.shiftKey && e.code === 'KeyO' && selectedSlug) {
        e.preventDefault()
        useChat.getState().newChat(selectedSlug)
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
  }, [selectedSlug, onToggleLeft, onToggleRight])

  return (
    <>
      <Shell
        left={<FSSpine onToggleLeft={onToggleLeft} />}
        center={inReview
          ? <ReviewOverlay
              onBack={() => useReview.getState().close()}
              leftHidden={leftHidden}
              rightHidden={reviewChatHidden}
              onToggleLeft={onToggleLeft}
              onToggleRight={onToggleRight}
            />
          : <ChatPanel />}
        leftHidden={leftHidden}
        rightHidden={shellRightHidden}
      />

      {/* Floating context panel — fixed overlay, visible when not hidden.
          Never rendered in review mode: the third column (ReviewChatColumn)
          owns the right rail there. */}
      {!inReview && !shellRightHidden && rightToggleEnabled && (
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
      {!inReview && shellRightHidden && rightToggleEnabled && (
        <PanelToggle
          side="right"
          hidden={true}
          onClick={onToggleRight}
          className="edge-toggle right"
        />
      )}
      <PromptQuickLook />
    </>
  )
}
