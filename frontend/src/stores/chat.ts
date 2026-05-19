import { create } from 'zustand'

import {
  getChatEvents,
  getChatList,
  getUnboundChatEvents,
  listUnboundChats,
  resolveAskUser,
  resolvePermission,
  rewindChat,
  type AskUserAnswerEntry,
  type ChatSummary,
  type UnboundChatSummary,
} from '../lib/api'
import { newChatId } from '../lib/ids'
import { pathForChatId, pathForSlug } from '../lib/slugUrl'
import { dispatchUiAction } from '../lib/surfaceRouter'
import { attachStream, cancelTurn, fetchTurnState, startTurn, type StartTurnBody } from '../lib/turn'
import type { ChatEvent } from '../types/chat'
import { useApiKey } from './apiKey'
import { useDocs } from './docs'
import { useEval } from './eval'
import { useExperiments } from './experiments'
import { useModels } from './models'
import { useProjects } from './projects'
import { usePrompts } from './prompts'
import { useSchema } from './schema'

const ACTIVE_CHAT_ID_KEY_PREFIX = 'emerge.activeChatId.'
const LEGACY_CHAT_ID_KEY_PREFIX = 'emerge.chatId.'   // pre-M8 single-chat key

/** Sentinel `projectId` value for the unbound-chat code path. Callers that
 *  hit `send()` from `/c/<cid>` or from the empty hero pass this so the
 *  store routes to `POST /lab/chats/{cid}/turn` instead of the legacy
 *  `POST /lab/chat` (with `project_id: 'p_unset'`). Matches the backend
 *  `_UNBOUND_SLUG` constant. */
export const UNBOUND_SLUG = '_chats'

// Process-lifetime fallback when localStorage is unavailable (SSR / incognito).
const _memChatIds = new Map<string, string>()

function _readChatId(projectId: string): string | null {
  try {
    const fresh = localStorage.getItem(ACTIVE_CHAT_ID_KEY_PREFIX + projectId)
    if (fresh) return fresh
    // One-shot migration: copy the legacy single-chat key forward to the
    // multi-chat active key, but leave the legacy key in place for one session
    // so a rollback (or older tab) still finds the original chat.
    const legacy = localStorage.getItem(LEGACY_CHAT_ID_KEY_PREFIX + projectId)
    if (legacy) {
      localStorage.setItem(ACTIVE_CHAT_ID_KEY_PREFIX + projectId, legacy)
      return legacy
    }
    return null
  } catch {
    return _memChatIds.get(projectId) ?? null
  }
}

function _writeChatId(projectId: string, chatId: string): void {
  try {
    localStorage.setItem(ACTIVE_CHAT_ID_KEY_PREFIX + projectId, chatId)
  } catch {
    _memChatIds.set(projectId, chatId)
  }
}

/** Per-project, persisted chat id. Mints + persists one on first access. */
function chatIdFor(projectId: string): string {
  const existing = _readChatId(projectId)
  if (existing) return existing
  const fresh = newChatId()
  _writeChatId(projectId, fresh)
  return fresh
}

// Per-chat in-flight turn id. Persisted under `turn:{chatId}` so that a reload
// (T6) can call `fetchTurnState` and decide whether to re-attach. Matches the
// same fallback-to-process-memory shape as `_readChatId` for SSR / incognito.
const TURN_ID_KEY_PREFIX = 'turn:'
const _memTurnIds = new Map<string, string>()

function _readTurnId(chatId: string): string | null {
  try {
    return localStorage.getItem(TURN_ID_KEY_PREFIX + chatId)
  } catch {
    return _memTurnIds.get(chatId) ?? null
  }
}

function _writeTurnId(chatId: string, turnId: string): void {
  try {
    localStorage.setItem(TURN_ID_KEY_PREFIX + chatId, turnId)
  } catch {
    _memTurnIds.set(chatId, turnId)
  }
}

function _clearTurnId(chatId: string): void {
  try {
    localStorage.removeItem(TURN_ID_KEY_PREFIX + chatId)
  } catch {
    _memTurnIds.delete(chatId)
  }
}

/** Snapshot of the active surface's UI state at message-submit time, threaded
 *  into the chat envelope so the backend can inject a `## Surface context`
 *  block in the system prompt. The snapshot MUST be taken at submit time
 *  (not at render time) — the user may navigate mid-response, and the
 *  agent's tool calls must bind to what they were looking at when they hit
 *  Enter.
 *
 *  Phase 1 only `surface: 'review'` exists; ambient navigation fields (page,
 *  page_count, etc.) are filled in opportunistically when the snapshotter has
 *  them. */
export interface SurfaceContext {
  surface: 'review'  // phase 2 will add 'home' | 'schema' | ...
  // ── review identity ──
  filename: string
  field?: string | null
  current_value?: unknown
  entity_index?: number
  // ── ambient navigation (review) ──
  page?: number
  page_count?: number
  entity_count?: number
  /** 'active' for the saved annotation tab; otherwise an experiment_id. */
  active_tab_key?: string
  /** Non-null iff `active_tab_key !== 'active'`. */
  experiment_id?: string | null
}

interface State {
  chatId: string
  events: ChatEvent[]
  busy: boolean
  loadedProjectId: string | null
  /** Non-null iff the active conversation is an *unbound* chat (`/c/<cid>`
   *  route or pre-submit empty hero). Mutually exclusive with
   *  `loadedProjectId` once set — promotion or project-pick clears it. The
   *  value equals `chatId` while loaded; storing it explicitly lets `send()`
   *  pick the unbound URL even after a hydrate race. */
  loadedUnboundChatId: string | null
  chatsByProject: Record<string, ChatSummary[]>
  /** Recent unbound chats (newest-first). Powers the empty-hero strip and
   *  the popover in unbound + `/` modes. Refreshed on demand via
   *  `listUnbound()`. */
  chatsUnbound: UnboundChatSummary[]
  /** Live abort controller for the SSE GET stream only — never the backend
   *  turn. Renamed from `abort` in M11 T5 to make the new semantics explicit:
   *  aborting this kills the tail-f subscription, not the agent loop. The
   *  agent loop is killed exclusively via `cancel()` → POST cancel. Null
   *  when no stream is attached. */
  streamAbort: AbortController | null
  /** Registry-assigned id of the live turn on this chat, or null if no turn
   *  is in flight (or the last turn ended naturally). Persisted under
   *  `turn:{chatId}` so a re-enter (T6) or reload can call `fetchTurnState`
   *  and decide whether to re-attach. Lifecycle methods (`enterProject` etc.)
   *  detach the stream but DO NOT clear `inflightTurnId` — the OLD chat's
   *  slice keeps it so the user can come back and re-tail. */
  inflightTurnId: string | null
  /** True iff the most recent turn was cancelled by the user (Stop/Esc) and
   *  no new send has reset state. The next send — whether via composer, retry,
   *  or edit-save — must rewind the chat log first so the abandoned user
   *  message + partial agent response are dropped rather than stacking. */
  interrupted: boolean
  /** Send a turn. `attachments` carries the doc handles for this message.
   *  Filename is the only post-pid handle; `stage_token` is the pre-pid
   *  bridge (the backend's chat_turn claims each token into chat-scope and
   *  persists `{filename, source: "chat"}`). `source` defaults to "chat"
   *  for paste/drop; reserved `"docs"` value is for future explicit-promote
   *  refs but not yet emitted by the composer.
   *  `surfaceContext` is the submit-time snapshot of whichever surface the
   *  user is on (only review in phase 1). Present only for sends from a
   *  surface that snapshots; main-shell ChatPanel callers must pass
   *  undefined; their behavior is unchanged. */
  send: (projectId: string, message: string, attachments?: { filename: string; stage_token?: string; source?: 'chat' | 'docs' }[], surfaceContext?: SurfaceContext) => Promise<void>
  /** Drop the user message at `userIndex` (0-indexed ordinal among user
   *  events) + everything after, locally and on disk, clear the SDK session
   *  sidecar, then re-send `text` as a fresh turn. `userIndex` omitted →
   *  targets the *last* user message. `attachments` re-carries the original
   *  message's chat-scope handles so the agent sees the same image blocks on
   *  the re-run (files in `chats/<chat_id>/attachments/` survive rewind).
   *  Powers retry (text = original) / edit-save (text = edited). No-op when busy. */
  rewindAndSend: (projectId: string, text: string, userIndex?: number, attachments?: { filename: string; source?: 'chat' | 'docs' }[]) => Promise<void>
  /** Cancel the in-flight turn (Stop button / Esc). Idempotent when idle.
   *  M11 T5: explicit POST to the cancel endpoint — closing SSE alone is
   *  no longer cancellation. */
  cancel: () => void
  /** Internal: detach the SSE GET stream without cancelling the turn. Called
   *  by lifecycle methods (`enterProject` / `switchChat` / `enterUnboundChat`
   *  / `newChat` / `deselect`) when the user navigates away mid-turn. Leaves
   *  `inflightTurnId` on the OLD chat's slice + its localStorage entry, so a
   *  later re-enter (T6) can re-attach. Set `busy: false` so the NEW chat
   *  doesn't inherit a stale spinner — the active chat after detach is the
   *  one we're about to load, and it has no turn in flight. */
  _detachStream: () => void
  enterProject: (projectId: string) => void
  /** Bind the chat shell to an existing unbound chat id (URL = `/c/<cid>`).
   *  Reuses the project-mode hydrate / race-safety pattern from
   *  `enterProject`, but pulls events from `GET /lab/chats/{cid}/events`. */
  enterUnboundChat: (chatId: string) => void
  /** Mint a fresh local unbound-chat id and clear events. Doesn't hit the
   *  backend — the first SSE turn / `POST /lab/chats/{cid}/turn` is what
   *  materialises storage. Matches the lazy "new chat" pattern on the
   *  project side. */
  newUnboundChat: () => string
  deselect: () => void
  listChats: (projectId: string) => Promise<void>
  /** Refresh the unbound-chat summary list. Permissive — degrades to empty
   *  on failure. */
  listUnbound: () => Promise<void>
  switchChat: (projectId: string, chatId: string) => void
  newChat: (projectId: string) => void
  lastUserMessage: () => string | null
  hasRecentToolError: () => boolean
  /** Resolve a pending SDK `can_use_tool` ask-user round-trip. Flips the
   *  matching `permission_request` event's local `resolution` field so the
   *  card re-renders in its resolved state, then POSTs the user's decision
   *  to the backend. Idempotent — a second call on an already-resolved
   *  event is a no-op. */
  resolvePermission: (requestId: string, decision: 'approve' | 'deny', scope: 'once' | 'always') => Promise<void>
  /** Submit the user's answer to an in-flight `ask_user_request`. Optimistic
   *  local flip of the event's `resolution` field so the AskUserCard
   *  immediately renders its "answered" trail, then POSTs to the backend
   *  resolver. Idempotent on a second click for an already-answered card. */
  resolveAskUser: (requestId: string, answers: AskUserAnswerEntry[]) => Promise<void>
  /** Mark any pending ask_user as user-redirected (cancelled). Fired
   *  internally by `send()` when the user types a new message while a card
   *  is pending — agent receives `ask_user_cancelled` and falls back to
   *  plain conversation. Resolves silently if there is no pending card. */
  cancelAskUser: (requestId: string, reason?: string) => Promise<void>
}

export const useChat = create<State>((set, get) => ({
  chatId: newChatId(),
  events: [],
  busy: false,
  loadedProjectId: null,
  loadedUnboundChatId: null,
  chatsByProject: {},
  chatsUnbound: [],
  streamAbort: null,
  inflightTurnId: null,
  interrupted: false,
  cancel: () => {
    // Stop button / Esc. Explicit cancel: POST to the cancel endpoint
    // (server-side `asyncio.Task.cancel`), then abort the SSE GET so the
    // stream closes promptly (the server will also flush a terminating
    // envelope, but waiting for it would leave `busy: true` flicker). The
    // POST is fire-and-forget — backend is idempotent and returns 200 even
    // on unknown turn_id, but we still want to proceed past a network glitch.
    const { chatId, inflightTurnId, streamAbort } = get()
    if (inflightTurnId) {
      void cancelTurn(chatId, inflightTurnId).catch(err => {
        console.warn('cancelTurn failed', err)
      })
      _clearTurnId(chatId)
    }
    if (streamAbort) streamAbort.abort()
    set({ interrupted: true, busy: false, streamAbort: null, inflightTurnId: null })
  },
  _detachStream: () => {
    // Lifecycle methods call this when the user navigates away from a chat
    // that has a live turn streaming. We close the SSE GET so the network
    // doesn't keep delivering events into the (about-to-be-replaced) chat
    // slice, but we deliberately leave `inflightTurnId` (+ its localStorage
    // entry) in place — re-entering the same chat (T6) calls
    // `fetchTurnState` and re-attaches via that id. `busy: false` because
    // the active chat after detach is the NEW one, which has no turn.
    const a = get().streamAbort
    if (a) a.abort()
    set({ streamAbort: null, busy: false })
  },
  rewindAndSend: async (projectId, text, userIndex, attachments) => {
    if (get().busy) return
    // rewindAndSend owns the rewind; clear the flag so send() doesn't try to
    // rewind a second time on the (already-cleaned) tail.
    set({ interrupted: false })
    try {
      await rewindChat(projectId, get().chatId, userIndex)
    } catch (e) {
      set(s => ({
        events: [...s.events, {
          type: 'error',
          error_code: 'rewind_failed',
          error_message_en: e instanceof Error ? e.message : String(e),
        }],
      }))
      return
    }
    // Local truncate: find the Nth user event (or the last when undefined),
    // drop it and everything after.
    set(s => {
      const userIdxs: number[] = []
      for (let i = 0; i < s.events.length; i++) {
        if (s.events[i].type === 'user') userIdxs.push(i)
      }
      if (userIdxs.length === 0) return s
      const ordinal = typeof userIndex === 'number' ? userIndex : userIdxs.length - 1
      if (ordinal < 0 || ordinal >= userIdxs.length) return s
      return { events: s.events.slice(0, userIdxs[ordinal]) }
    })
    await get().send(projectId, text, attachments)
  },
  enterProject: (projectId) => {
    if (projectId === 'p_unset') return
    if (projectId === get().loadedProjectId) return

    // Create-project-from-EmptyHero case: there was no loaded project yet but an
    // in-flight conversation already exists — that conversation *is* this project's
    // first chat. Adopt it and persist the current chatId under the new project key
    // (keep get().chatId rather than minting a fresh one, so the server log written
    // under that chatId stays reachable on a later reload). Do not clear, do not hydrate.
    //
    // Same shape applies to the unbound→promoted case: a `/c/<cid>` chat that
    // was just promoted lands here via `useProjects.select(slug)` after the
    // backend relocates the jsonl from `_chats/` to `<slug>/chats/`. The chat
    // events already on disk under the new slug match the in-memory tail, so
    // we adopt rather than re-hydrate. `loadedUnboundChatId` is cleared so
    // future `send()` calls hit the per-project endpoint.
    if (
      (get().loadedProjectId === null || get().loadedUnboundChatId !== null)
      && get().events.length > 0
    ) {
      _writeChatId(projectId, get().chatId)
      set({ loadedProjectId: projectId, loadedUnboundChatId: null })
      return
    }

    // Real project switch (or first entry into a project with no in-flight convo):
    // bind to that project's persisted chatId, clear, then fire-and-forget hydrate.
    // M11 T5: detach the SSE before we flip slice fields — the OLD chat's
    // turn (if any) is registry-resident on the backend and stays running;
    // its `inflightTurnId` survives in the OLD chat's localStorage key so a
    // later re-enter (T6) can re-attach.
    //
    // M11 T13: localStorage is a hint, not authoritative. We use `chatIdFor`
    // synchronously to avoid a round-trip on the cold path, but then refine
    // by listing chats server-side and — if the cached id is missing from
    // the list, or a more-recent chat exists — silently switch to it. This
    // lets a second device / CLI client open the same project and land on
    // the same chat without any cross-device sync mechanism.
    get()._detachStream()
    const cid = chatIdFor(projectId)
    set({
      loadedProjectId: projectId,
      loadedUnboundChatId: null,
      chatId: cid,
      events: [],
      busy: false,
      interrupted: false,
      inflightTurnId: _readTurnId(cid),
    })
    // Snapshot the prefix length right after the clear so the apply branch can
    // tell whether the user sent anything during the hydration window. If they
    // did, events.length will have grown past prefixLen → prepend rather than
    // replace, so the user's in-flight tail isn't silently dropped.
    const prefixLen = get().events.length
    void (async () => {
      const reduced = reduceEvents(await getChatEvents(projectId, cid))
      set(s => {
        // User switched away during the fetch → drop the result entirely.
        if (s.chatId !== cid || s.loadedProjectId !== projectId) return s
        // Common case: nothing happened between dispatch and apply → replace.
        if (s.events.length === prefixLen) return { events: reduced }
        // User sent during hydration → prepend server history, keep in-flight tail.
        return { events: [...reduced, ...s.events] }
      })
      // M11 T6: after hydrate installs, probe turn_state and re-attach if the
      // backend still has a live turn for this chat. Race-guarded inside.
      if (useChat.getState().chatId === cid && useChat.getState().loadedProjectId === projectId) {
        void _maybeReattach(cid, projectId)
      }
    })()
    // M11 T13 refinement: fire-and-forget list chats, then reconcile.
    // - If the cached cid is present in the returned list → keep, refresh popover.
    // - Else if list is non-empty → switch to chats[0] (backend sorts ts_iso desc).
    // - Else (list is empty) → keep the freshly-minted cid; nothing to do.
    // `switchChat` already owns detach + clear + hydrate + race-safety, so
    // we delegate to it for the swap path. The race-guard re-checks chatId +
    // loadedProjectId after the await so a user who has already navigated
    // away doesn't get yanked back.
    void (async () => {
      await get().listChats(projectId)
      const cur = useChat.getState()
      if (cur.loadedProjectId !== projectId) return
      const list = cur.chatsByProject[projectId] ?? []
      if (list.length === 0) return
      // Still on the originally-bound cid? Only swap if user hasn't manually
      // moved to a different chat (e.g. via switchChat or newChat) during
      // the await. If they have, leave their explicit pick alone.
      if (cur.chatId !== cid) return
      if (list.some(c => c.chat_id === cid)) return
      const latest = list[0].chat_id
      if (latest === cid) return
      get().switchChat(projectId, latest)
    })()
  },
  enterUnboundChat: (chatId) => {
    if (chatId === get().loadedUnboundChatId) return
    // Adopt-in-flight: a fresh empty-hero conversation that already streamed
    // a first turn is *this* unbound chat by construction — the SSE turn ran
    // with `chat_id=get().chatId`, which we now rebind to the URL-provided
    // id. (In practice the URL was just pushed from `send()` so the values
    // already match, but the guard keeps the assertion explicit.)
    if (
      get().loadedProjectId === null
      && get().loadedUnboundChatId === null
      && get().events.length > 0
      && chatId === get().chatId
    ) {
      set({ loadedUnboundChatId: chatId })
      return
    }
    // Fresh entry / switch: clear, then fire-and-forget hydrate. Same
    // race-safety pattern as enterProject — snapshot prefixLen so an in-flight
    // user message during hydration isn't trampled.
    // M11 T5: detach the SSE for the OLD chat (if any), but don't touch the
    // OLD chat's `turn:{cid}` localStorage — that lets re-enter (T6) re-attach.
    get()._detachStream()
    set({
      loadedProjectId: null,
      loadedUnboundChatId: chatId,
      chatId,
      events: [],
      busy: false,
      interrupted: false,
      inflightTurnId: _readTurnId(chatId),
    })
    const prefixLen = get().events.length
    void (async () => {
      const reduced = reduceEvents(await getUnboundChatEvents(chatId))
      set(s => {
        if (s.chatId !== chatId || s.loadedUnboundChatId !== chatId) return s
        if (s.events.length === prefixLen) return { events: reduced }
        return { events: [...reduced, ...s.events] }
      })
      // M11 T6: same re-attach probe as the project branch. Unbound mode
      // passes UNBOUND_SLUG so _maybeReattach checks loadedUnboundChatId.
      if (useChat.getState().chatId === chatId && useChat.getState().loadedUnboundChatId === chatId) {
        void _maybeReattach(chatId, UNBOUND_SLUG)
      }
    })()
    void get().listUnbound()
  },
  newUnboundChat: () => {
    // Mint a fresh local chat id. Storage isn't created until the first
    // SSE turn — same lazy posture as the project-side `newChat`. Caller is
    // responsible for navigating to `/c/<cid>` once it wants the URL bar in
    // sync; this action just resets the in-memory shell so the next `send()`
    // hits an empty conversation under the new id.
    //
    // M11 T5: detach any in-flight stream from the previous chat. The
    // previous chat's `inflightTurnId` localStorage entry stays — re-entering
    // it later can still re-attach.
    get()._detachStream()
    const fresh = newChatId()
    set({
      loadedProjectId: null,
      loadedUnboundChatId: fresh,
      chatId: fresh,
      events: [],
      busy: false,
      interrupted: false,
      inflightTurnId: null,
    })
    return fresh
  },
  deselect: () => {
    // Reset to the no-project-loaded baseline. Used when the user clicks
    // "+ new project…" (selectedId → null) so the conv column doesn't keep
    // showing the previous project's events. Fresh chatId so the next
    // enterProject's adopt branch (loadedProjectId === null + events.length>0)
    // works cleanly for any immediate in-flight conversation.
    //
    // Important: `deselect` is also fired when the user is on `/c/<cid>` and
    // the URL→store sync flips `selectedSlug` to null. In that case we must
    // NOT clobber an active unbound load — checking `loadedUnboundChatId`
    // keeps the unbound conversation intact while still clearing any stale
    // project binding.
    if (get().loadedUnboundChatId) {
      set({ loadedProjectId: null })
      return
    }
    // M11 T5: this branch fully resets to the empty baseline, so the
    // previous chat's stream (if any) must detach. Its `inflightTurnId`
    // stays on localStorage so re-entering that chat by URL still works.
    get()._detachStream()
    set({
      events: [],
      busy: false,
      loadedProjectId: null,
      loadedUnboundChatId: null,
      chatId: newChatId(),
      interrupted: false,
      inflightTurnId: null,
    })
  },
  listChats: async (projectId) => {
    if (projectId === 'p_unset') return
    const list = await getChatList(projectId)
    set(s => ({ chatsByProject: { ...s.chatsByProject, [projectId]: list } }))
  },
  listUnbound: async () => {
    const list = await listUnboundChats()
    set({ chatsUnbound: list })
  },
  switchChat: (projectId, chatId) => {
    if (projectId === 'p_unset') return
    if (chatId === get().chatId) return
    // M11 T5: detach the previous chat's SSE before we flip slice fields.
    // The old chat's turn keeps running on the backend; its `inflightTurnId`
    // remains in localStorage so coming back re-attaches.
    get()._detachStream()
    _writeChatId(projectId, chatId)
    set({
      loadedProjectId: projectId,
      chatId,
      events: [],
      busy: false,
      interrupted: false,
      inflightTurnId: _readTurnId(chatId),
    })
    // Same in-flight-tail race-safety pattern as enterProject's switch branch:
    // snapshot prefixLen post-clear, re-check chatId + loadedProjectId on apply.
    const prefixLen = get().events.length
    void (async () => {
      const reduced = reduceEvents(await getChatEvents(projectId, chatId))
      set(s => {
        if (s.chatId !== chatId || s.loadedProjectId !== projectId) return s
        if (s.events.length === prefixLen) return { events: reduced }
        return { events: [...reduced, ...s.events] }
      })
      // M11 T6: probe turn_state and re-attach if the backend still has a
      // live turn. Race-guarded inside _maybeReattach as well.
      if (useChat.getState().chatId === chatId && useChat.getState().loadedProjectId === projectId) {
        void _maybeReattach(chatId, projectId)
      }
    })()
  },
  newChat: (projectId) => {
    if (projectId === 'p_unset') return
    // M11 T5: detach the previous chat's SSE. Its `inflightTurnId` (if any)
    // stays in localStorage so the user can switch back and re-attach.
    get()._detachStream()
    const fresh = newChatId()
    _writeChatId(projectId, fresh)
    set({
      loadedProjectId: projectId,
      chatId: fresh,
      events: [],
      busy: false,
      interrupted: false,
      inflightTurnId: null,
    })
  },
  lastUserMessage: () => {
    const events = get().events
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i]
      if (e.type === 'user') return e.text
    }
    return null
  },
  hasRecentToolError: () => {
    const events = get().events
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i]
      if (e.type === 'user') return false
      if (e.type === 'tool_call' && e.ok === false) return true
      if (e.type === 'error') return true
    }
    return false
  },
  cancelAskUser: async (requestId, _reason) => {
    let already = false
    set(s => ({
      events: s.events.map(e => {
        if (e.type === 'ask_user_request' && e.request_id === requestId) {
          if (e.resolution) {
            already = true
            return e
          }
          return { ...e, resolution: { answers: [], cancelled: true } }
        }
        return e
      }),
    }))
    if (already) return
    const chatId = get().chatId
    try {
      await resolveAskUser(chatId, requestId, { answers: [], cancelled: true })
    } catch (err) {
      console.warn('cancelAskUser failed', err)
    }
  },
  resolveAskUser: async (requestId, answers) => {
    let already = false
    set(s => ({
      events: s.events.map(e => {
        if (e.type === 'ask_user_request' && e.request_id === requestId) {
          if (e.resolution) {
            already = true
            return e
          }
          return { ...e, resolution: { answers } }
        }
        return e
      }),
    }))
    if (already) return
    const chatId = get().chatId
    try {
      await resolveAskUser(chatId, requestId, { answers })
    } catch (err) {
      // Same fail-open posture as resolvePermission — local card is already
      // in its answered state; if the backend never receives it, the agent's
      // await resolves via cancel_pending_ask_user at turn end with an
      // ask_user_cancelled envelope.
      console.warn('resolveAskUser failed', err)
    }
  },
  resolvePermission: async (requestId, decision, scope) => {
    // Optimistic local flip first — the card must show "approved/denied" the
    // instant the user clicks, regardless of network latency. The backend
    // resolve is idempotent so a duplicate click (from a stale render) is
    // safely swallowed.
    let already = false
    set(s => ({
      events: s.events.map(e => {
        if (e.type === 'permission_request' && e.request_id === requestId) {
          if (e.resolution) {
            already = true
            return e
          }
          return { ...e, resolution: { decision, scope } }
        }
        return e
      }),
    }))
    if (already) return
    const chatId = get().chatId
    try {
      await resolvePermission(chatId, requestId, { decision, scope })
    } catch (err) {
      // Swallow — the local card is already in its resolved state. If the
      // backend never received the decision the agent's await will eventually
      // surface as a turn-level error, which has its own error event.
      console.warn('resolvePermission failed', err)
    }
  },
  send: async (projectId, message, attachments, surfaceContext) => {
    // M11 T5: send is now a two-phase operation. Phase 1 (preflight +
    // ``startTurn``) returns a ``turn_id`` immediately; phase 2
    // (``_consumeStream``) tail-fs the turn's SSE stream. The two are
    // separable so that lifecycle methods (``enterProject`` etc.) can detach
    // the SSE without killing the backend turn — see ``_detachStream``.
    //
    // Three logical slug shapes coexist for the turn:
    //   - project mode      → real slug
    //   - unbound mode      → `_chats` (UNBOUND_SLUG)
    //   - legacy p_unset    → `p_unset` (back-compat; new code routes to
    //     UNBOUND_SLUG for empty-hero, but the backend still accepts it).
    // All three flow through ``POST /lab/chats/{cid}/turns`` — the slug is
    // a body field, not a URL component.
    const isUnbound = projectId === UNBOUND_SLUG

    // Capture the new pid emitted by the backend when chat_turn auto-mints a
    // project from a `p_unset` + stage_token submission. Held in a ref so
    // the stream-consumer can mutate it from inside the event loop and the
    // ``finally`` cleanup can read the final value. The in-memory `events`
    // array is left untouched on mint (adopt semantics).
    const mintedPidRef: { value: string | null } = { value: null }

    // Mid-prompt redirect: if an ask_user card is still waiting on a pick and
    // the user typed into the composer instead, treat the new message as a
    // redirect. POST cancel-ask-user so the agent's tool await resolves to
    // ``ask_user_cancelled``. M11 T5: also POST the explicit turn cancel
    // before opening a new turn — the user is choosing to abandon the old
    // line of thinking. (Without this the old turn would keep running in the
    // backend until something else cancels it.) Then close the SSE GET so
    // the new turn can open cleanly. We intentionally do NOT set
    // ``interrupted=true`` — that path rewinds the last user message, which
    // would drop the original question and the agent's ask_user trail.
    const pendingAsk = get().events.find(
      e => e.type === 'ask_user_request' && !e.resolution,
    )
    if (pendingAsk && pendingAsk.type === 'ask_user_request') {
      await get().cancelAskUser(pendingAsk.request_id, 'User redirected via composer.')
      const { chatId: redirCid, inflightTurnId: redirTid, streamAbort: redirAbort } = get()
      if (redirTid) {
        void cancelTurn(redirCid, redirTid).catch(err => {
          console.warn('cancelTurn (mid-prompt redirect) failed', err)
        })
        _clearTurnId(redirCid)
      }
      if (redirAbort) redirAbort.abort()
      set({ busy: false, streamAbort: null, interrupted: false, inflightTurnId: null })
    }

    // First message into a freshly-selected real project: bind loadedProjectId and
    // persist the current chatId under that project key, so a later enterProject for
    // the same id is a correct no-op and a reload restores the binding. For unbound
    // mode the analogue is `loadedUnboundChatId` — if a caller pushed the user into
    // `send()` without going through `enterUnboundChat` / `newUnboundChat` (e.g.
    // empty-hero first message), bind it now so the URL sync + popover scope agree.
    if (isUnbound) {
      if (get().loadedUnboundChatId === null) {
        set({ loadedUnboundChatId: get().chatId, loadedProjectId: null })
      }
    } else if (projectId !== 'p_unset' && get().loadedProjectId === null) {
      _writeChatId(projectId, get().chatId)
      set({ loadedProjectId: projectId, loadedUnboundChatId: null })
    }
    // Consume the interrupted flag: if the last turn was cancelled, drop its
    // user message + partial agent tail before sending the new turn. This
    // makes composer-after-Stop visually equivalent to retry — the rewind
    // endpoint accepts `p_unset` and `_chats` alongside committed slugs, so
    // pre-adoption / unbound chats clean up identically.
    if (get().interrupted) {
      try {
        await rewindChat(projectId, get().chatId)
      } catch {
        // Server-side rewind failed — local truncate still proceeds; if the
        // log on disk drifts, getChatEvents hydration is permissive (skips
        // junk lines) so render won't crash.
      }
      set(s => {
        let lastUserIdx = -1
        for (let i = s.events.length - 1; i >= 0; i--) {
          if (s.events[i].type === 'user') { lastUserIdx = i; break }
        }
        if (lastUserIdx < 0) return { interrupted: false }
        return { events: s.events.slice(0, lastUserIdx), interrupted: false }
      })
    }
    // Filename is the only doc handle now — keep entries that have a non-empty
    // filename, drop pre-upload placeholders (no real filename yet). Backend
    // applies the same filter when persisting.
    // For the local optimistic event we only render filename — stage_tokens
    // are an in-flight implementation detail that get rewritten to {filename}
    // by chat_turn before the user line lands in events.jsonl, so the local
    // view stays consistent with the persisted log.
    const userAttachments = (attachments ?? [])
      .filter(a => typeof a.filename === 'string' && a.filename.length > 0)
      .map(a => ({ filename: a.filename, source: a.source ?? 'chat' as const }))
    // Push the optimistic user event before `startTurn` resolves so the
    // composer empties immediately and the UI doesn't appear to swallow the
    // submit. `events.length` at this point is the offset we'll later pass
    // to `attachStream` as `after_offset` — the stream catches up everything
    // appended on the backend after our optimistic line.
    set(s => ({
      events: [
        ...s.events,
        userAttachments.length > 0
          ? { type: 'user', text: message, attachments: userAttachments }
          : { type: 'user', text: message },
      ],
      busy: true,
    }))

    // Phase 1: start the turn (HTTP POST, returns turn_id).
    const cid = get().chatId
    const startBody: StartTurnBody = {
      slug: projectId,
      user_message: message,
      attachments,
      ...(surfaceContext ? { surface_context: surfaceContext } : {}),
    }
    let turnId: string
    try {
      const resp = await startTurn(cid, startBody)
      turnId = resp.turn_id
    } catch (e) {
      // Couldn't even start the turn — surface as an error event and bail.
      // The optimistic user line stays so the user can retry / edit; matches
      // the legacy posture of treating start-time failures as soft errors.
      set(s => ({
        events: [...s.events, {
          type: 'error',
          error_code: 'turn_start_failed',
          error_message_en: e instanceof Error ? e.message : String(e),
        }],
        busy: false,
      }))
      return
    }

    // After offset captures the local count of events before stream attach —
    // any chunks the backend already appended to events.jsonl beyond this
    // point will be replayed by the route layer when we GET the stream.
    const afterOffset = get().events.length
    const abortCtrl = new AbortController()
    _writeTurnId(cid, turnId)
    set({ streamAbort: abortCtrl, inflightTurnId: turnId })

    // Phase 2: consume the stream. Returns `streamEndedNaturally=true` only
    // when a `turn_end` was reached or the iterator completed without abort;
    // `false` on abort (lifecycle detach OR cancel()). We use that flag to
    // decide whether `finally` should clear `inflightTurnId` — a plain
    // detach must NOT clear it, because re-entering the chat needs to be
    // able to re-attach (T6).
    let streamEndedNaturally = false
    try {
      const result = await _consumeStream(
        cid, turnId, afterOffset, abortCtrl, projectId, mintedPidRef,
      )
      streamEndedNaturally = result.streamEndedNaturally
    } catch (e) {
      // _consumeStream re-raises non-abort errors. Treat them as natural
      // termination of THIS send() — the turn is done from the FE's POV
      // and we won't be coming back to re-attach.
      streamEndedNaturally = true
      throw e
    } finally {
      // Clear streamAbort always — the controller is single-use. Clearing
      // `inflightTurnId` is conditional: only when the stream ended of its
      // own accord (turn_end consumed) or via an exception that propagated.
      // A plain SSE abort (from `_detachStream`) leaves `inflightTurnId`
      // on the slice — the caller of `_detachStream` has already swapped
      // the slice to the new chat by the time we run this `finally`, so
      // writing `inflightTurnId: null` here would clobber the new chat's
      // slice (which has its own `inflightTurnId` from `_readTurnId`).
      // ``cancel()`` clears the turn id itself, so its detach path lands
      // here with `streamEndedNaturally=false` and we correctly avoid
      // touching the now-empty `inflightTurnId`.
      if (streamEndedNaturally) {
        // Only touch state if this chat is still the active one — a lifecycle
        // detach + re-enter might have brought a different chat into focus.
        const curState = get()
        if (curState.chatId === cid) {
          set({ busy: false, streamAbort: null, inflightTurnId: null })
        }
        _clearTurnId(cid)
      } else {
        // Stream ended via abort. If this chat is still active, the abort
        // came from `cancel()` (which already cleared streamAbort) — be
        // idempotent. If not, the slice has already swapped; leave
        // `inflightTurnId` alone on the new chat.
        const curState = get()
        if (curState.chatId === cid && curState.streamAbort === abortCtrl) {
          // Defensive — `cancel()` should have set this null already, but
          // a future caller might forget.
          set({ streamAbort: null })
        }
      }
      // After a `p_unset` submission that auto-minted a project, refresh the
      // chat list under the new pid (the chat is now logged there). For
      // unbound mode the analogue is `listUnbound()` — the unbound roster
      // gained a new entry (or its label/ts moved on an existing entry).
      // Only fire these on natural end, otherwise we spam fetches when a
      // user switches view mid-turn.
      if (streamEndedNaturally) {
        const finalPid = mintedPidRef.value ?? projectId
        if (isUnbound && mintedPidRef.value === null) {
          void get().listUnbound()
        } else if (finalPid !== 'p_unset' && finalPid !== UNBOUND_SLUG) {
          void get().listChats(finalPid)
        }
      }
    }
  },
}))

/**
 * Drain the SSE stream for ``turnId`` and dispatch each event into the chat
 * slice. Mirrors the pre-M11 event-dispatch branches verbatim — the only
 * difference is the source of the events (``attachStream`` GET vs. the old
 * ``streamSSE`` POST). Returns ``streamEndedNaturally=true`` iff we saw a
 * ``turn_end`` envelope (or the iterator completed without exception);
 * ``false`` when ``signal.aborted`` is what closed us. Non-abort exceptions
 * propagate so ``send()`` can decide.
 */
async function _consumeStream(
  cid: string,
  turnId: string,
  afterOffset: number,
  abortCtrl: AbortController,
  projectId: string,
  mintedPidRef: { value: string | null },
): Promise<{ streamEndedNaturally: boolean }> {
  try {
    for await (const ev of attachStream(cid, turnId, {
      after_offset: afterOffset,
      signal: abortCtrl.signal,
    })) {
      if (ev.event === 'tool_result') {
        const d = ev.data as { tool_use_id: string; result_text: string; ok: boolean }
        handleToolResult(d, mintedPidRef.value ?? projectId, _findRecentVersionId())
        continue
      }
      if (ev.event === 'ui_action') {
        // Out-of-band navigation push from the agent's ui_* tools. The
        // router resolves `action` (e.g. 'review:goto_page') to the
        // appropriate store mutation. Best-effort: if router rejects the
        // params or the surface is wrong, we swallow — the user's main
        // chat experience must not stall on a navigation glitch.
        try {
          dispatchUiAction(ev.data)
        } catch (err) {
          console.warn('ui_action dispatch failed', err)
        }
        continue
      }
      if (ev.event === 'project_minted') {
        // Agent-3 emits all three handles on project_minted so the FE can
        // pick whichever is most convenient. We use `slug` (or
        // `project_id` as the legacy-compatible alias — values match).
        const d = ev.data as { project_id: string; slug?: string; pid?: string; name: string }
        const slug = d.slug ?? d.project_id
        mintedPidRef.value = slug
        // Persist chatId under the new slug, mark loadedProjectId before the
        // ChatPanel useEffect re-runs (so enterProject's same-slug early
        // return fires instead of the clear-and-hydrate path), refresh
        // projects, then flip selectedSlug. The current chat events stay in
        // place — they are this project's first chat by construction.
        _writeChatId(slug, useChat.getState().chatId)
        useChat.setState({ loadedProjectId: slug })
        void useProjects.getState().refresh()
        useProjects.getState().select(slug)
        void useChat.getState().listChats(slug)
        // Staged docs are already on disk in the new project's docs/ —
        // surface them in FSSpine right away, without waiting for the
        // agent's first list_docs tool_result.
        void useDocs.getState().refresh(slug)
        continue
      }
      if (ev.event === 'ask_user_request') {
        // ``ask_user`` MCP tool blocks on a per-(chat_id, request_id) future
        // server-side. Push the event into the conv log so AskUserCard can
        // render the structured Q&A; resolveAskUser() resolves the future
        // when the user clicks an option. Like permission_request, nothing
        // here is persisted server-side — a reload during the prompt drops
        // the card and cancel_pending_ask_user releases the agent's await
        // with an ask_user_cancelled envelope.
        const d = ev.data as {
          request_id: string
          questions: import('../types/chat').AskUserQuestion[]
        }
        useChat.setState(s => ({
          events: [
            ...s.events,
            {
              type: 'ask_user_request',
              request_id: d.request_id,
              questions: d.questions,
            },
          ],
        }))
        continue
      }
      if (ev.event === 'permission_request') {
        // SDK `can_use_tool` ask-user round-trip — the agent's tool call
        // is suspended on the backend awaiting our reply. Push the event
        // into the conv log; PermissionCard renders the approve/deny UI
        // and dispatches resolvePermission() when the user clicks. The
        // resolution lands on this same event object (no separate
        // `permission_resolved` SSE — the backend doesn't echo, just
        // releases the future). Reload-permissive: nothing here gets
        // written to events.jsonl (server-side filter), so a refresh
        // mid-prompt drops the card and the agent's awaited future will
        // resolve via `cancel_pending` at turn end.
        const d = ev.data as {
          request_id: string
          tool_name: string
          tool_input: unknown
          reason: string
          suggested_scope?: 'once' | 'always'
        }
        useChat.setState(s => ({
          events: [
            ...s.events,
            {
              type: 'permission_request',
              request_id: d.request_id,
              tool_name: d.tool_name,
              tool_input: d.tool_input,
              reason: d.reason,
              suggested_scope: d.suggested_scope ?? 'once',
            },
          ],
        }))
        continue
      }
      if (ev.event === 'project_renamed') {
        // Agent called `rename_project` mid-turn — the on-disk slug has
        // changed and chat_turn already rerouted post-rename appends to
        // the new path. Mirror that on the FE: re-point selectedSlug
        // (triggers App.tsx's URL sync to push /p/{new_slug}), move our
        // activeChatId mapping to the new slug, and refresh projects so
        // the sidebar shows the new name. The conversation array stays
        // intact (mapped events are already in `s.events`).
        const d = ev.data as { old_slug: string; new_slug: string }
        if (d.new_slug && d.new_slug !== d.old_slug) {
          const renameCid = useChat.getState().chatId
          if (renameCid) _writeChatId(d.new_slug, renameCid)
          mintedPidRef.value = d.new_slug
          useChat.setState({ loadedProjectId: d.new_slug })
          void useProjects.getState().refresh()
          useProjects.getState().select(d.new_slug)
          void useChat.getState().listChats(d.new_slug)
          void useDocs.getState().refresh(d.new_slug)
        }
        continue
      }
      const mapped = mapSse(ev.event, ev.data)
      if (mapped === null) continue   // ignored event (user_acknowledged etc.)
      if (mapped.type === 'turn_end') {
        return { streamEndedNaturally: true }
      }
      useChat.setState(s => ({ events: [...s.events, mapped] }))
    }
  } catch (e) {
    // User-initiated abort (`_detachStream` or `cancel`) surfaces as
    // AbortError — return cleanly so the caller can branch on
    // `streamEndedNaturally=false`. Anything else propagates.
    const aborted = abortCtrl.signal.aborted
      || (e instanceof DOMException && e.name === 'AbortError')
      || (e instanceof Error && e.name === 'AbortError')
    if (!aborted) throw e
    return { streamEndedNaturally: false }
  }
  // Iterator exhausted without seeing turn_end (shouldn't happen — registry
  // always sends a sentinel — but treat as natural close).
  return { streamEndedNaturally: true }
}

/**
 * M11 T6: after a lifecycle method (``enterProject`` / ``enterUnboundChat`` /
 * ``switchChat``) hydrates a chat from disk, check whether the backend still
 * has a live turn for this chat — if so, attach a fresh SSE stream at
 * ``after_offset = events.length`` so the user sees the live tail again.
 *
 * Called from inside the hydrate IIFE *after* the hydrated events have been
 * installed via ``set``. The IIFE's race-safety guard (chatId + project match)
 * has already filtered out switch-during-hydrate cases. We re-check the same
 * invariants here because ``fetchTurnState`` is another async hop and the
 * user may have switched again during it.
 *
 * Best-effort: any network/state mismatch falls through silently to "treat
 * this chat as static history". The OLD chat's ``inflightTurnId`` localStorage
 * entry is cleared on confirmed-done/stale paths so we don't keep retrying
 * a dead turn on every re-enter.
 *
 * The mintedPidRef passed into ``_consumeStream`` is a fresh ``{value: null}``
 * — capturing a mid-turn ``project_minted`` is essentially impossible on
 * re-attach (the turn started in this same project / unbound chat and the
 * mint already happened or didn't). A clean ref is the right default.
 */
async function _maybeReattach(cid: string, projectId: string): Promise<void> {
  const localTurnId = _readTurnId(cid)
  if (!localTurnId) return

  let state
  try {
    state = await fetchTurnState(cid)
  } catch (err) {
    // Network / 5xx — leave the local entry as-is so a later re-enter can
    // retry. The chat falls back to static-history behaviour for now.
    console.warn('fetchTurnState failed on re-attach probe', err)
    return
  }

  // Turn no longer registered backend-side (registry evicted post-finish, or
  // backend restart wiped state). The jsonl hydrate is authoritative.
  if (state.active_turn_id === null) {
    _clearTurnId(cid)
    return
  }
  // Stale local id — a different turn is live now (could happen if a CLI
  // client started a new turn while this client was offline). Don't attach;
  // wipe the stale local so the next re-enter doesn't keep stumbling on it.
  if (state.active_turn_id !== localTurnId) {
    _clearTurnId(cid)
    return
  }
  // Turn already terminated — jsonl hydrate has the final state; nothing to
  // tail. (Backend keeps a brief window of finished entries in registry for
  // late-attaching clients to read the terminal envelope, but on re-enter we
  // already have the final events on disk.)
  if (state.status === 'done' || state.status === 'cancelled' || state.status === 'error') {
    _clearTurnId(cid)
    return
  }
  if (state.status !== 'running') return

  // Race-check: did the user switch chats while fetchTurnState was in flight?
  // The hydrate IIFE has its own guard, but we ran AFTER it, and ours is an
  // independent async hop. Bail if focus moved.
  const cur = useChat.getState()
  if (cur.chatId !== cid) return
  // Project mode → require loadedProjectId match. Unbound mode → require
  // loadedUnboundChatId match. Same shape as the hydrate IIFEs.
  const isUnbound = projectId === UNBOUND_SLUG
  if (isUnbound) {
    if (cur.loadedUnboundChatId !== cid) return
  } else {
    if (cur.loadedProjectId !== projectId) return
  }

  const afterOffset = cur.events.length
  const ctrl = new AbortController()
  useChat.setState({ busy: true, streamAbort: ctrl })

  const mintedPidRef: { value: string | null } = { value: null }
  let streamEndedNaturally = false
  try {
    const result = await _consumeStream(
      cid, localTurnId, afterOffset, ctrl, projectId, mintedPidRef,
    )
    streamEndedNaturally = result.streamEndedNaturally
  } catch (e) {
    streamEndedNaturally = true
    throw e
  } finally {
    // Same conditional-clear posture as send()'s finally: only wipe
    // inflightTurnId when the stream ended of its own accord. A detach
    // (user switched again mid-reattach) leaves the entry so the NEXT
    // re-enter can try again.
    if (streamEndedNaturally) {
      const cur2 = useChat.getState()
      if (cur2.chatId === cid) {
        useChat.setState({ busy: false, streamAbort: null, inflightTurnId: null })
      }
      _clearTurnId(cid)
    } else {
      const cur2 = useChat.getState()
      if (cur2.chatId === cid && cur2.streamAbort === ctrl) {
        useChat.setState({ streamAbort: null })
      }
    }
  }
}

function _findRecentVersionId(): string | null {
  const events = useChat.getState().events
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i]
    if (e.type !== 'tool_call' || e.tool_name !== 'mcp__emerge_tools__freeze_version') continue
    if (typeof e.tool_result === 'string') {
      try {
        return (JSON.parse(e.tool_result) as { version_id?: string }).version_id ?? null
      } catch {
        return null
      }
    }
    if (e.tool_result && typeof e.tool_result === 'object') {
      return (e.tool_result as { version_id?: string }).version_id ?? null
    }
    break
  }
  return null
}

function handleToolResult(
  d: { tool_use_id: string; result_text: string; ok: boolean },
  projectId: string,
  versionId: string | null,
) {
  const events = useChat.getState().events
  const parent = events.find(e => e.type === 'tool_call' && e.tool_use_id === d.tool_use_id)
  let resultPayload: unknown = d.result_text

  if (parent?.type === 'tool_call' && parent.tool_name === 'mcp__emerge_tools__issue_api_key') {
    try {
      const parsed = JSON.parse(d.result_text) as {
        key_plaintext?: string
        key_hash?: string
        key_prefix?: string
        created_at?: string
        error?: { error_code: string; error_message_en: string }
      }
      if (parsed.error) {
        useChat.setState(s => ({
          events: [...s.events, {
            type: 'error',
            error_code: parsed.error!.error_code,
            error_message_en: parsed.error!.error_message_en,
          }],
        }))
        resultPayload = { redacted: true, error: parsed.error.error_code }
      } else if (parsed.key_plaintext && parsed.key_hash && parsed.key_prefix && parsed.created_at) {
        useApiKey.getState().setReveal({
          key_plaintext: parsed.key_plaintext,
          key_hash: parsed.key_hash,
          key_prefix: parsed.key_prefix,
          created_at: parsed.created_at,
          project_id: projectId,
          version_id: versionId,
        })
        resultPayload = {
          redacted: true,
          key_prefix: parsed.key_prefix,
          key_hash_short: parsed.key_hash.slice(-6),
          created_at: parsed.created_at,
        }
      }
    } catch {
      resultPayload = { redacted: true, error: 'parse_failed' }
    }
  }

  useChat.setState(s => ({
    events: s.events.map(e => {
      if (e.type === 'tool_call' && e.tool_use_id === d.tool_use_id) {
        return { ...e, tool_result: resultPayload, ok: d.ok }
      }
      return e
    }),
  }))

  // Cross-store invalidation: when a schema-mutating or fs-mutating tool succeeds,
  // the lab stores need to refetch so the UI doesn't drift from the workspace.
  if (parent?.type === 'tool_call' && d.ok) {
    const t = parent.tool_name
    if (t === 'mcp__emerge_tools__write_schema' || t === 'mcp__emerge_tools__accept_candidate') {
      useSchema.getState().invalidate(projectId)
      usePrompts.getState().invalidate(projectId)
      void usePrompts.getState().load(projectId)
    }
    if (
      t === 'mcp__emerge_tools__write_prompt' ||
      t === 'mcp__emerge_tools__create_prompt' ||
      t === 'mcp__emerge_tools__switch_active_prompt' ||
      t === 'mcp__emerge_tools__delete_prompt' ||
      t === 'mcp__emerge_tools__import_prompt'
    ) {
      useSchema.getState().invalidate(projectId)
      usePrompts.getState().invalidate(projectId)
      void usePrompts.getState().load(projectId)
    }
    if (
      t === 'mcp__emerge_tools__write_model' ||
      t === 'mcp__emerge_tools__create_model' ||
      t === 'mcp__emerge_tools__switch_active_model' ||
      t === 'mcp__emerge_tools__delete_model'
    ) {
      useModels.getState().invalidate(projectId)
      void useModels.getState().load(projectId)
    }
    if (
      t === 'mcp__emerge_tools__upload_doc' ||
      t === 'mcp__emerge_tools__save_reviewed' ||
      t === 'mcp__emerge_tools__extract_batch' ||
      t === 'mcp__emerge_tools__extract_one' ||
      // pre_label writes reviewed/_pending/ drafts. Doc-list badges don't
      // change (pending status is independent of has_prediction/has_reviewed),
      // but if a review tab is open on a freshly pre-labeled doc the banner
      // needs the pending payload — re-fetching docs is the simplest cache
      // bump that propagates to the FSSpine list. The banner itself loads
      // lazily on useReview.open().
      t === 'mcp__emerge_tools__pre_label'
    ) {
      void useDocs.getState().refresh(projectId)
    }
    if (
      t === 'mcp__emerge_tools__create_project' ||
      t === 'mcp__emerge_tools__rename_project' ||
      t === 'mcp__emerge_tools__freeze_version' ||
      t === 'mcp__emerge_tools__fork_project'
    ) {
      void useProjects.getState().refresh()
      // Agent-side promote: when `create_project` was invoked from inside an
      // unbound chat (the agent's reading of `from_unbound_chat_id`), the
      // backend has already relocated this chat's jsonl + attachments under
      // the new project. Flip the FE binding so subsequent turns go through
      // the per-project path and the URL bar updates to `/p/<slug>`. The
      // input shape is `{name, from_unbound_chat_id, ...}` — if the latter
      // matches our active unbound chat, adopt.
      if (t === 'mcp__emerge_tools__create_project'
          && useChat.getState().loadedUnboundChatId
      ) {
        const input = parent.tool_input as { from_unbound_chat_id?: unknown } | null
        const result = resultPayload as { slug?: unknown } | string | null
        const slugRaw = (result && typeof result === 'object')
          ? (result as { slug?: unknown }).slug
          : null
        if (
          input
          && typeof input.from_unbound_chat_id === 'string'
          && input.from_unbound_chat_id === useChat.getState().loadedUnboundChatId
          && typeof slugRaw === 'string'
          && slugRaw.length > 0
        ) {
          const slug = slugRaw
          // Persist the current chatId under the new slug key so reload-restore
          // hits the existing jsonl rather than minting a fresh chat.
          _writeChatId(slug, useChat.getState().chatId)
          useChat.setState({ loadedProjectId: slug, loadedUnboundChatId: null })
          useProjects.getState().select(slug)
          // Refresh the unbound roster — the now-promoted chat should drop
          // out of it.
          void useChat.getState().listUnbound()
        }
      }
    }
    if (t === 'mcp__emerge_tools__score') {
      void useEval.getState().refresh(projectId)
    }
    if (
      t === 'mcp__emerge_tools__create_experiment' ||
      t === 'mcp__emerge_tools__archive_experiment' ||
      t === 'mcp__emerge_tools__delete_experiment' ||
      t === 'mcp__emerge_tools__run_experiment_eval'
    ) {
      useExperiments.getState().invalidate(projectId)
      void useExperiments.getState().load(projectId)
    }
    if (t === 'mcp__emerge_tools__promote_experiment') {
      // promote_experiment flips active prompt+model AND re-seeds predictions/_draft
      useExperiments.getState().invalidate(projectId)
      void useExperiments.getState().load(projectId)
      useSchema.getState().invalidate(projectId)
      usePrompts.getState().invalidate(projectId)
      void usePrompts.getState().load(projectId)
      useModels.getState().invalidate(projectId)
      void useModels.getState().load(projectId)
      void useDocs.getState().refresh(projectId)
    }
    // extract_with_experiment writes to experiment's extracts (doc-scoped, handled
    // in useReview T13) — no project-scoped store refresh needed here.
  }
}

/**
 * Reduce a raw chat JSONL log (one object per line) into the in-memory ChatEvent[]
 * the UI renders. Pure & side-effect-free — this is *passive replay*, not live
 * actions, so it deliberately does NOT run handleToolResult's side effects
 * (no API-key reveal modal, no cross-store invalidation). `tool_call` and
 * `tool_result` arrive on separate lines and are paired here by `tool_use_id`.
 */

/** Reshape the persist-side issue_api_key result_text (a JSON string with
 *  key_plaintext already redacted) into the same trail shape SSE produces:
 *  {redacted, key_prefix, key_hash_short, created_at} on success, or
 *  {redacted, error} on backend error / unparseable. Never throws. */
function _hydrateIssueApiKeyResult(raw: unknown): unknown {
  if (typeof raw !== 'string') return raw ?? null
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return { redacted: true, error: 'parse_failed' }
  }
  if (!parsed || typeof parsed !== 'object') return { redacted: true, error: 'parse_failed' }
  const p = parsed as Record<string, unknown>
  const err = p.error as { error_code?: unknown } | undefined
  if (err && typeof err === 'object' && typeof err.error_code === 'string') {
    return { redacted: true, error: err.error_code }
  }
  const kp = typeof p.key_prefix === 'string' ? p.key_prefix : null
  const kh = typeof p.key_hash === 'string' ? p.key_hash : null
  const ca = typeof p.created_at === 'string' ? p.created_at : null
  if (kp && kh && ca) {
    return { redacted: true, key_prefix: kp, key_hash_short: kh.slice(-6), created_at: ca }
  }
  return { redacted: true, error: 'parse_failed' }
}

export function reduceEvents(raw: unknown[]): ChatEvent[] {
  const out: ChatEvent[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const o = item as Record<string, unknown>
    switch (o.type) {
      case 'user': {
        const ev: ChatEvent = { type: 'user', text: String(o.text ?? '') }
        const rawAtts = o.attachments
        if (Array.isArray(rawAtts)) {
          const atts = rawAtts
            .map(x => x && typeof x === 'object' ? x as Record<string, unknown> : null)
            .filter((x): x is Record<string, unknown> =>
              x !== null && typeof x.filename === 'string' && (x.filename as string).length > 0,
            )
            .map(x => ({
              filename: x.filename as string,
              source: x.source === 'docs' ? 'docs' as const : 'chat' as const,
            }))
          if (atts.length > 0) ev.attachments = atts
        }
        out.push(ev)
        break
      }
      case 'agent_text':
        out.push({ type: 'agent_text', text: String(o.text ?? '') })
        break
      case 'error':
        out.push({
          type: 'error',
          error_code: String(o.error_code ?? ''),
          error_message_en: String(o.error_message_en ?? ''),
        })
        break
      case 'tool_call':
        out.push({
          type: 'tool_call',
          tool_use_id: typeof o.tool_use_id === 'string' ? o.tool_use_id : undefined,
          tool_name: String(o.tool_name ?? ''),
          tool_input: o.tool_input,
          tool_result: null,
          ok: typeof o.ok === 'boolean' ? o.ok : true,
        })
        break
      case 'tool_result': {
        const tuid = o.tool_use_id
        if (typeof tuid !== 'string') break
        // Most-recent matching tool_call already accumulated.
        for (let i = out.length - 1; i >= 0; i--) {
          const e = out[i]
          if (e.type === 'tool_call' && e.tool_use_id === tuid) {
            // For issue_api_key: reshape the persist-side JSON-string into the
            // same {redacted, key_prefix, key_hash_short, created_at} trail
            // SSE handleToolResult emits — so PublishStageKeyAdapter sees one
            // object shape across both code paths. Pure (no useApiKey reveal).
            e.tool_result = e.tool_name === 'mcp__emerge_tools__issue_api_key'
              ? _hydrateIssueApiKeyResult(o.result_text)
              : (o.result_text ?? null)
            e.ok = typeof o.ok === 'boolean' ? o.ok : true
            break
          }
        }
        // Orphan tool_result (no matching tool_call) → dropped.
        break
      }
      default:
        // turn_end / unknown — skip.
        break
    }
  }
  return out
}

export const _testUtils = { handleToolResult, reduceEvents, chatIdFor }

function mapSse(event: string, data: unknown): ChatEvent | null {
  if (event === 'agent_text') return { type: 'agent_text', text: (data as { text: string }).text }
  if (event === 'tool_call') {
    const d = data as { tool_use_id?: string; tool_name: string; tool_input: unknown; tool_result: unknown; ok?: boolean }
    return {
      type: 'tool_call',
      tool_use_id: d.tool_use_id,
      tool_name: d.tool_name,
      tool_input: d.tool_input,
      tool_result: d.tool_result,
      ok: d.ok ?? true,
    }
  }
  if (event === 'error') {
    const d = data as { error_code: string; error_message_en: string }
    return { type: 'error', error_code: d.error_code, error_message_en: d.error_message_en }
  }
  if (event === 'turn_end') return { type: 'turn_end' }
  // user_acknowledged / system / unknown — ignored. Returning null lets
  // future event types pass through silently rather than corrupt the chat.
  return null
}
