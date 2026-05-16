import { create } from 'zustand'

import { getChatEvents, getChatList, rewindChat, type ChatSummary } from '../lib/api'
import { newChatId } from '../lib/ids'
import { streamSSE } from '../lib/sse'
import { dispatchUiAction } from '../lib/surfaceRouter'
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
  chatsByProject: Record<string, ChatSummary[]>
  /** Live abort controller for the in-flight SSE turn; null when idle. */
  abort: AbortController | null
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
  /** Cancel the in-flight turn (Stop button / Esc). Idempotent when idle. */
  cancel: () => void
  enterProject: (projectId: string) => void
  deselect: () => void
  listChats: (projectId: string) => Promise<void>
  switchChat: (projectId: string, chatId: string) => void
  newChat: (projectId: string) => void
  lastUserMessage: () => string | null
  hasRecentToolError: () => boolean
}

export const useChat = create<State>((set, get) => ({
  chatId: newChatId(),
  events: [],
  busy: false,
  loadedProjectId: null,
  chatsByProject: {},
  abort: null,
  interrupted: false,
  cancel: () => {
    const a = get().abort
    if (!a) return
    a.abort()
    set({ interrupted: true })
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
    if (get().loadedProjectId === null && get().events.length > 0) {
      _writeChatId(projectId, get().chatId)
      set({ loadedProjectId: projectId })
      return
    }

    // Real project switch (or first entry into a project with no in-flight convo):
    // bind to that project's persisted chatId, clear, then fire-and-forget hydrate.
    const cid = chatIdFor(projectId)
    set({ loadedProjectId: projectId, chatId: cid, events: [], busy: false, interrupted: false })
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
    })()
    // Fire-and-forget: refresh the chat list so the conv-header popover has
    // server-authoritative entries for this project.
    void get().listChats(projectId)
  },
  deselect: () => {
    // Reset to the no-project-loaded baseline. Used when the user clicks
    // "+ new project…" (selectedId → null) so the conv column doesn't keep
    // showing the previous project's events. Fresh chatId so the next
    // enterProject's adopt branch (loadedProjectId === null + events.length>0)
    // works cleanly for any immediate in-flight conversation.
    set({ events: [], busy: false, loadedProjectId: null, chatId: newChatId(), interrupted: false })
  },
  listChats: async (projectId) => {
    if (projectId === 'p_unset') return
    const list = await getChatList(projectId)
    set(s => ({ chatsByProject: { ...s.chatsByProject, [projectId]: list } }))
  },
  switchChat: (projectId, chatId) => {
    if (projectId === 'p_unset') return
    if (chatId === get().chatId) return
    _writeChatId(projectId, chatId)
    set({ loadedProjectId: projectId, chatId, events: [], busy: false, interrupted: false })
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
    })()
  },
  newChat: (projectId) => {
    if (projectId === 'p_unset') return
    const fresh = newChatId()
    _writeChatId(projectId, fresh)
    set({ loadedProjectId: projectId, chatId: fresh, events: [], busy: false, interrupted: false })
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
  send: async (projectId, message, attachments, surfaceContext) => {
    // Capture the new pid emitted by the backend when chat_turn auto-mints a
    // project from a `p_unset` + stage_token submission. We listen for the
    // `project_minted` SSE event and re-bind on the fly: localStorage chatId
    // moves under the new pid, selectedId flips, and the projects list
    // refreshes. The in-memory `events` array is left untouched (adopt
    // semantics — the user/agent_text/tool events already pushed are this
    // project's first chat).
    let mintedPid: string | null = null

    // First message into a freshly-selected real project: bind loadedProjectId and
    // persist the current chatId under that project key, so a later enterProject for
    // the same id is a correct no-op and a reload restores the binding.
    if (projectId !== 'p_unset' && get().loadedProjectId === null) {
      _writeChatId(projectId, get().chatId)
      set({ loadedProjectId: projectId })
    }
    // Consume the interrupted flag: if the last turn was cancelled, drop its
    // user message + partial agent tail before sending the new turn. This
    // makes composer-after-Stop visually equivalent to retry — the abandoned
    // bubble doesn't stack. The rewind endpoint accepts `p_unset` too, so
    // pre-adoption chats clean up identically.
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
    const abortCtrl = new AbortController()
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
    set(s => ({
      events: [
        ...s.events,
        userAttachments.length > 0
          ? { type: 'user', text: message, attachments: userAttachments }
          : { type: 'user', text: message },
      ],
      busy: true,
      abort: abortCtrl,
    }))
    try {
      for await (const ev of streamSSE('/lab/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          chat_id: get().chatId,
          user_message: message,
          attachments,
          // Only sent when the user submits from a surface that snapshots
          // state (currently: review overlay's compact chat column).
          // Backend treats absence as the pre-Phase-B path (no
          // `## Surface context` block in system prompt).
          ...(surfaceContext ? { surface_context: surfaceContext } : {}),
        }),
        signal: abortCtrl.signal,
      })) {
        if (ev.event === 'tool_result') {
          const d = ev.data as { tool_use_id: string; result_text: string; ok: boolean }
          handleToolResult(d, mintedPid ?? projectId, _findRecentVersionId())
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
          mintedPid = slug
          // Persist chatId under the new slug, mark loadedProjectId before the
          // ChatPanel useEffect re-runs (so enterProject's same-slug early
          // return fires instead of the clear-and-hydrate path), refresh
          // projects, then flip selectedSlug. The current chat events stay in
          // place — they are this project's first chat by construction.
          _writeChatId(slug, get().chatId)
          set({ loadedProjectId: slug })
          void useProjects.getState().refresh()
          useProjects.getState().select(slug)
          void get().listChats(slug)
          // Staged docs are already on disk in the new project's docs/ —
          // surface them in FSSpine right away, without waiting for the
          // agent's first list_docs tool_result.
          void useDocs.getState().refresh(slug)
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
            const cid = get().chatId
            if (cid) _writeChatId(d.new_slug, cid)
            mintedPid = d.new_slug
            set({ loadedProjectId: d.new_slug })
            void useProjects.getState().refresh()
            useProjects.getState().select(d.new_slug)
            void get().listChats(d.new_slug)
            void useDocs.getState().refresh(d.new_slug)
          }
          continue
        }
        const mapped = mapSse(ev.event, ev.data)
        if (mapped === null) continue   // ignored event (user_acknowledged etc.)
        if (mapped.type === 'turn_end') break
        set(s => ({ events: [...s.events, mapped] }))
      }
    } catch (e) {
      // User-initiated cancel surfaces as AbortError — silent. Anything else re-raises.
      const aborted = abortCtrl.signal.aborted
        || (e instanceof DOMException && e.name === 'AbortError')
        || (e instanceof Error && e.name === 'AbortError')
      if (!aborted) throw e
    } finally {
      set({ busy: false, abort: null })
      // After a `p_unset` submission that auto-minted a project, refresh the
      // chat list under the new pid (the chat is now logged there).
      const finalPid = mintedPid ?? projectId
      if (finalPid !== 'p_unset') void get().listChats(finalPid)
    }
  },
}))

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
      t === 'mcp__emerge_tools__extract_one'
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
