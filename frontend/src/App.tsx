import { useState, useEffect, useCallback } from 'react'
import Shell from './components/Shell/Shell'
import FSSpine from './components/Spine/FSSpine'
import ChatPanel from './components/Chat/ChatPanel'
import ContextSurface from './components/Context/ContextSurface'
import ReviewOverlay from './components/ReviewMode/ReviewOverlay'
import PromptQuickLook from './components/QuickLook/PromptQuickLook'
import PanelToggle from './components/Shell/PanelToggle'
import EvalMatrixPage from './components/EvalMatrix/EvalMatrixPage'
import EvalCompare from './components/EvalMatrix/EvalCompare'
import { useReview } from './stores/review'
import { useProjects } from './stores/projects'
import { useChat } from './stores/chat'
import {
  pathForChatId,
  pathForSlug,
  readChatIdFromPathname,
  readEvalRouteFromUrl,
  readSlugFromPathname,
} from './lib/slugUrl'

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
  // M12 — eval matrix / compare are standalone pages that bypass the chat
  // shell entirely. Read the URL on every render so popstate from the matrix
  // back-link does the right thing without wiring react-router yet.
  const [evalRoute, setEvalRoute] = useState(() =>
    readEvalRouteFromUrl(window.location.pathname, window.location.search),
  )
  useEffect(() => {
    const onPop = () => {
      setEvalRoute(
        readEvalRouteFromUrl(window.location.pathname, window.location.search),
      )
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const { activeFilename } = useReview()
  const { selectedSlug } = useProjects()
  const loadedUnboundChatId = useChat(s => s.loadedUnboundChatId)

  if (evalRoute && evalRoute.kind === 'eval') {
    return <EvalMatrixPage slug={evalRoute.slug} ts={evalRoute.ts} />
  }
  if (evalRoute && evalRoute.kind === 'compare') {
    return <EvalCompare slug={evalRoute.slug} a={evalRoute.a} b={evalRoute.b} />
  }

  // URL ↔ store sync.
  //
  // Three address shapes now coexist:
  //   `/`             → empty hero, no project, no unbound chat
  //   `/p/<slug>`     → project-bound conversation
  //   `/c/<cid>`      → unbound conversation (lives under workspace/_chats/)
  //
  // The frontend has no router despite the `react-router-dom` dep — selection
  // lives in two Zustand stores (`useProjects.selectedSlug`,
  // `useChat.loadedUnboundChatId`) so the address bar stays decorative unless
  // we keep it in lock-step here. The handler does three things:
  //   (a) on mount: read the URL once and hydrate whichever store applies
  //   (b) on `selectedSlug` / `loadedUnboundChatId` change: pushState
  //   (c) on browser back/forward (`popstate`): re-read the URL into the
  //       relevant store, clearing the other so we don't end up in an
  //       inconsistent both-set / both-clear state.
  useEffect(() => {
    const path = window.location.pathname
    const initialSlug = readSlugFromPathname(path)
    const initialChatId = readChatIdFromPathname(path)
    if (initialSlug) {
      useProjects.getState().select(initialSlug)
    } else if (initialChatId) {
      useChat.getState().enterUnboundChat(initialChatId)
    }
    const onPop = () => {
      const p = window.location.pathname
      const slug = readSlugFromPathname(p)
      const cid = readChatIdFromPathname(p)
      if (slug) {
        useProjects.getState().select(slug)
      } else if (cid) {
        useProjects.getState().select(null)
        useChat.getState().enterUnboundChat(cid)
      } else {
        // Root: clear both selections so the empty hero renders. We have to
        // null the unbound binding explicitly first — `deselect()` is
        // unbound-aware and would otherwise preserve any active
        // `loadedUnboundChatId`.
        useChat.setState({ loadedUnboundChatId: null })
        useProjects.getState().select(null)
        useChat.getState().deselect()
      }
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  useEffect(() => {
    // Project route wins when both stores claim a binding — `selectedSlug` is
    // set by the promote-flow before the unbound id clears, so checking it
    // first keeps the URL stable through the `/c/<cid>` → `/p/<slug>` swap.
    let target: string
    if (selectedSlug) {
      target = pathForSlug(selectedSlug, window.location.search, window.location.hash)
    } else if (loadedUnboundChatId) {
      target = pathForChatId(loadedUnboundChatId, window.location.search, window.location.hash)
    } else {
      target = pathForSlug(null, window.location.search, window.location.hash)
    }
    const current = window.location.pathname + window.location.search + window.location.hash
    if (target !== current) {
      window.history.pushState(null, '', target)
    }
  }, [selectedSlug, loadedUnboundChatId])

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
      // Cmd/Ctrl+1..5 → jump to the Nth most-recent unbound conversation
      // from the empty-hero strip. Active only at `/` (no slug, no unbound
      // chat loaded yet) — otherwise the user is already inside a chat and
      // the same shortcuts would be a surprise switch. Mirrors the strip's
      // visible `⌘N` hints.
      if (!e.shiftKey && !selectedSlug && !loadedUnboundChatId) {
        const digit = e.code.startsWith('Digit') ? e.code.slice(5) : ''
        const idx = digit ? parseInt(digit, 10) - 1 : -1
        if (idx >= 0 && idx <= 4) {
          const list = useChat.getState().chatsUnbound
          const target = list[idx]
          if (target) {
            e.preventDefault()
            useChat.getState().enterUnboundChat(target.chat_id)
            return
          }
        }
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [selectedSlug, loadedUnboundChatId, onToggleLeft, onToggleRight])

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
