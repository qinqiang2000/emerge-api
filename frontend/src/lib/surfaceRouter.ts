// Surface action router — receives `ui_action` SSE events from the agent and
// dispatches them to the right zustand store. Phase 1 only handles the four
// review-mode navigation actions; the wire format is shared with the backend
// `ui_actions` tools (`app/tools/ui_actions.py`).
//
// Kept deliberately dumb: a switch, not a registry. Validation is intentionally
// loose — the backend tool validates too, and the worst-case here is "we
// silently ignore a malformed nav command", which is preferable to crashing
// the chat stream.

import { useReview } from '../stores/review'
import { navigateToReview } from './slugUrl'

interface UiActionPayload {
  type?: string
  action: string
  params?: Record<string, unknown>
  ts?: number
}

function _asInt(x: unknown): number | null {
  if (typeof x === 'number' && Number.isFinite(x) && Math.floor(x) === x) return x
  return null
}

function _asString(x: unknown): string | null {
  return typeof x === 'string' && x.length > 0 ? x : null
}

/** Resolve one ui_action event. `data` is whatever the backend serialised under
 *  the `data:` line of the SSE frame (already JSON-parsed by streamSSE). */
export function dispatchUiAction(data: unknown): void {
  if (!data || typeof data !== 'object') return
  const payload = data as UiActionPayload
  if (typeof payload.action !== 'string') return
  const params = payload.params ?? {}
  switch (payload.action) {
    case 'review:open': {
      // Agent-side twin of clicking a doc row in the spine — URL push via
      // navigateToReview, so back-button history and the AppShell URL→store
      // sync behave exactly as a human click would.
      const slug = _asString(params.slug)
      const filename = _asString(params.filename)
      if (slug === null || filename === null) return
      navigateToReview(slug, filename)
      return
    }
    case 'review:goto_page': {
      const page = _asInt(params.page)
      if (page === null) return
      useReview.getState().goPage(page)
      return
    }
    case 'review:set_active_field': {
      const path = _asString(params.path)
      if (path === null) return
      // setActiveField has toggle semantics — clicking the active row clears
      // it. The router-set path is the agent's explicit "make this active"
      // intent; clear the store's current field first if it matches, so the
      // second-arg-toggle path doesn't no-op when the user repeats a request.
      const cur = useReview.getState().activeField
      if (cur === path) return
      useReview.getState().setActiveField(path)
      return
    }
    case 'review:set_active_tab': {
      const tab = _asString(params.tab_key)
      if (tab === null) return
      useReview.getState().setActiveTab(tab as 'active' | string)
      return
    }
    case 'review:set_active_entity': {
      const idx = _asInt(params.idx)
      if (idx === null || idx < 0) return
      useReview.getState().setActiveEntityIdx(idx)
      return
    }
    default:
      // Unknown action — ignore. Forward-compatible with future ui_actions.
      return
  }
}
