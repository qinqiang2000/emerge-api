// frontend/src/components/Chat/ChatPanel.tsx
import { useEffect, useRef, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'

import { attachToChat, promoteChat, stageUpload } from '../../lib/api'
import { useProjects } from '../../stores/projects'
import { useChat, UNBOUND_SLUG, type SurfaceContext } from '../../stores/chat'
import { useDocs } from '../../stores/docs'
import { useEvalSurface } from '../../stores/evalSurface'
import { useReview } from '../../stores/review'
import { useSchema } from '../../stores/schema'
import { useJob } from '../../stores/jobs'
import Composer from './Composer'
import ConvHeader from './ConvHeader'
import ChatErrorBoundary from './ChatErrorBoundary'
import MessageList from './MessageList'
import EmptyHero from '../Empty/EmptyHero'
import ImproveBanner from '../Improve/ImproveBanner'
import { useT } from '../../i18n'

/**
 * One pending attachment as the user sees it before the chat turn fires.
 *
 * - In an *empty-project* state (no `selectedSlug`) the file is uploaded
 *   immediately to `/lab/uploads/staging` (no pid required) → `stage_token`.
 *   We hang onto the original `File` handle so a failed upload can be
 *   retried without asking the user to re-drag the file.
 * - In a *selected-project* state the file is uploaded straight to
 *   `/lab/projects/{slug}/chats/{chatId}/attach` (chat-scoped scratch — NOT
 *   `docs/`) and surfaces the post-dedupe `filename`. Promotion into `docs/`
 *   is a separate user-acked agent call (`promote_attachment_to_docs`).
 *
 * `originalName` is what the chip started with — kept so we can match a
 * chip back to its in-flight upload when the server-side filename differs
 * after dedupe (concurrent uploads of the same `foo.pdf` → `foo (1).pdf`).
 *
 * Filename is the only doc handle now; there is no `doc_id`.
 */
interface AttachInfo {
  /** Display + key for the chip. Starts as `file.name`; after upload
   *  resolves, reconciled to the dedupe filename returned by the server. */
  filename: string
  originalName: string
  file: File
  status: 'staging' | 'staged' | 'uploading' | 'uploaded' | 'failed'
  stage_token?: string
  error?: string
}

interface ChatPanelProps {
  /** Compact mode — used by ReviewChatColumn so the chat fits into a narrow
   *  third column. Hides ConvHeader (history popover is reachable from the main
   *  shell when you exit review) and swaps EmptyHero for a one-line placeholder
   *  since the hero's hero-text wouldn't survive a 360px-wide column. */
  compact?: boolean
  /** Override the composer placeholder. Plumbed straight to <Composer />.
   *  Useful for surfaces with limited width (drilldown) where the default
   *  copy would wrap. */
  composerPlaceholder?: string
}

export default function ChatPanel({ compact = false, composerPlaceholder }: ChatPanelProps = {}) {
  const t = useT()
  const { selectedSlug, projects } = useProjects()
  const events = useChat(s => s.events)
  const send = useChat(s => s.send)
  const busy = useChat(s => s.busy)
  const chatId = useChat(s => s.chatId)
  const chatsByProject = useChat(s => s.chatsByProject)
  const loadedUnboundChatId = useChat(s => s.loadedUnboundChatId)
  const chatsUnbound = useChat(s => s.chatsUnbound)
  // Three header scopes — the popover uses `chats` to render its body, the
  // active scope label is one-word, no decorations (matches LeftSpine
  // selected-state pattern: subtle, ink-3 weight).
  //
  //   `/p/<slug>` → scope=project, chats = chatsByProject[slug]
  //   `/c/<cid>`  → scope=unbound, chats = chatsUnbound (active row marks current)
  //   `/`         → scope=unbound, chats = chatsUnbound (no active row)
  //
  // We hand the popover the full unbound roster in both unbound and root
  // cases; the active-row marker tracks via `currentChatId === c.chat_id`,
  // so a row only lights up when the user is actually in that chat.
  const isUnbound = !selectedSlug && !!loadedUnboundChatId
  const chats = selectedSlug
    ? (chatsByProject[selectedSlug] ?? [])
    : chatsUnbound
  // Composer carve-out: a pending ask_user card means the agent is awaiting
  // structured input, but the user must still be able to redirect via free
  // text. The store's send() detects the pending card and converts the new
  // message into an implicit cancel of the question before opening the next
  // turn. Permission cards keep the strict block — there's no "type your own
  // permission" semantic.
  const pendingAskUser = events.some(
    e => e.type === 'ask_user_request' && !e.resolution,
  )

  // Reload-restore: when a real project becomes selected, bind to its persisted
  // chatId and hydrate the chat log. enterProject is a no-op for 'p_unset' and
  // when already on this project, so the create-project flow is safe.
  //
  // `deselect` is unbound-aware: it preserves an active `loadedUnboundChatId`
  // so navigating from `/p/<slug>` → `/c/<cid>` (popover switch) keeps the
  // unbound conversation intact.
  useEffect(() => {
    if (selectedSlug) useChat.getState().enterProject(selectedSlug)
    else useChat.getState().deselect()
  }, [selectedSlug])

  // Empty-hero hint: when the user lands on `/` with no projects + no unbound
  // chat history, the popover strip is hidden and the hero handles intro.
  // Otherwise we kick off a one-shot listUnbound so the strip + popover render
  // without waiting for the first interaction.
  useEffect(() => {
    if (!compact && !selectedSlug) {
      void useChat.getState().listUnbound()
    }
  }, [compact, selectedSlug])
  const docCount = useDocs(s => (s.byProject[selectedSlug ?? ''] ?? []).length)
  const fieldCount = useSchema(s => (s.byProject[selectedSlug ?? ''] ?? []).length)
  const [pending, setPending] = useState<AttachInfo[]>([])
  const convScrollRef = useRef<HTMLDivElement>(null)
  // Stick-to-bottom: auto-follow streaming agent output, but back off when the
  // user has scrolled up to read history / copy a tool result. We track stick
  // state in a ref (not state) so the scroll handler doesn't re-render on
  // every wheel tick. Threshold is generous — small layout jiggles (tool
  // cards expanding, code blocks rendering) shouldn't break stick mode.
  const STICK_THRESHOLD_PX = 120
  const stickRef = useRef(true)

  // `hasContent` flips `.conv-scroll` (and `.conv-inner`) into the tree —
  // the scroll handler + ResizeObserver have to (re)attach when that happens,
  // not just at first mount.
  const hasContent = events.length > 0 || docCount > 0 || fieldCount > 0

  useEffect(() => {
    if (!hasContent) return
    const el = convScrollRef.current
    if (!el) return
    const onScroll = () => {
      const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
      stickRef.current = distFromBottom < STICK_THRESHOLD_PX
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    const inner = el.querySelector('.conv-inner') as HTMLElement | null

    // Catch in-place content growth — streaming text deltas mutate existing
    // nodes rather than bumping events.length, and a ResizeObserver on the
    // inner is the cheapest way to spot them. MutationObserver covers the
    // case where a tool result lazily attaches a tall child node.
    let ro: ResizeObserver | null = null
    let mo: MutationObserver | null = null
    const follow = () => {
      if (stickRef.current) el.scrollTop = el.scrollHeight
    }
    if (inner) {
      ro = new ResizeObserver(follow)
      ro.observe(inner)
      mo = new MutationObserver(follow)
      mo.observe(inner, { subtree: true, childList: true, characterData: true })
    }
    return () => {
      el.removeEventListener('scroll', onScroll)
      ro?.disconnect()
      mo?.disconnect()
    }
  }, [hasContent])

  // Discrete events (new turn, tool_call, busy flip) — pin to bottom on the
  // next frame so we read scrollHeight after React has committed the new
  // node. Streaming token-by-token deltas don't bump events.length; the
  // ResizeObserver above catches those.
  useEffect(() => {
    const el = convScrollRef.current
    if (!el || !stickRef.current) return
    const raf = requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight
    })
    return () => cancelAnimationFrame(raf)
  }, [events.length, busy])

  // Switching project or chat: reset stick mode and pin to bottom so the
  // newly-loaded conversation opens at the latest message, not wherever the
  // previous one was scrolled to.
  useEffect(() => {
    const el = convScrollRef.current
    if (!el) return
    stickRef.current = true
    el.scrollTop = el.scrollHeight
  }, [selectedSlug, chatId])

  // Find any running improve job to show the banner.
  const byId = useJob(useShallow(s => s.byId))
  const runningImproveEntry = Object.entries(byId)
    .filter(([, slice]) => slice.status === 'running')
    .sort(([a], [b]) => (a > b ? -1 : a < b ? 1 : 0))[0] ?? null
  const improveJob = runningImproveEntry ? runningImproveEntry[1] : null

  function handleBannerOpen() {
    // Scroll to the most recent proposal card via data-attribute, or fall back to bottom.
    const jobId = improveJob?.jobId
    const card = jobId
      ? document.querySelector(`[data-improve-card="${jobId}"]`)
      : null
    if (card) {
      card.scrollIntoView({ behavior: 'smooth', block: 'center' })
    } else {
      const el = convScrollRef.current
      if (el) el.scrollTop = el.scrollHeight
    }
  }

  const projectName = projects.find(p => p.slug === selectedSlug)?.name ?? ''

  /** Resolve a unique pending entry by filename + File identity (since two
   *  drops can share a name and we keep both rows visible). The File object
   *  identity uniquely identifies the drop. */
  function _matchPending(p: AttachInfo, filename: string, file: File): boolean {
    return p.filename === filename && p.file === file
  }

  async function _stageOne(file: File): Promise<void> {
    try {
      const info = await stageUpload(file)
      setPending(p => p.map(x => _matchPending(x, file.name, file)
        ? { ...x, status: 'staged', stage_token: info.stage_token, error: undefined }
        : x))
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setPending(p => p.map(x => _matchPending(x, file.name, file)
        ? { ...x, status: 'failed', error: msg }
        : x))
    }
  }

  async function _uploadOne(file: File, slug: string, cid: string): Promise<void> {
    try {
      const { filename } = await attachToChat(slug, cid, file)
      setPending(p => p.map(x => _matchPending(x, file.name, file)
        ? { ...x, status: 'uploaded', filename, error: undefined }
        : x))
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setPending(p => p.map(x => _matchPending(x, file.name, file)
        ? { ...x, status: 'failed', error: msg }
        : x))
    }
  }

  async function attach(files: File[]) {
    if (files.length === 0) return
    if (!selectedSlug) {
      // No project yet: stage each file under workspace/_staging/{token}/.
      // Chat turn will mint a project + claim the staged files into
      // chats/<chat_id>/attachments/ when the user submits.
      const initial = files.map<AttachInfo>(f => ({
        filename: f.name, originalName: f.name, file: f, status: 'staging',
      }))
      setPending(p => [...p, ...initial])
      await Promise.all(files.map(_stageOne))
      return
    }
    // Project selected: write to the current chat's attachments dir (NOT
    // docs/). Promotion to docs/ requires explicit user ack via the agent
    // tool `promote_attachment_to_docs`.
    const initial = files.map<AttachInfo>(f => ({
      filename: f.name, originalName: f.name, file: f, status: 'uploading',
    }))
    setPending(p => [...p, ...initial])
    await Promise.all(files.map(f => _uploadOne(f, selectedSlug, chatId)))
  }

  async function retry(index: number) {
    const target = pending[index]
    if (!target || target.status !== 'failed') return
    if (selectedSlug) {
      setPending(p => p.map((x, i) => i === index ? { ...x, status: 'uploading', error: undefined } : x))
      await _uploadOne(target.file, selectedSlug, chatId)
    } else {
      setPending(p => p.map((x, i) => i === index ? { ...x, status: 'staging', error: undefined } : x))
      await _stageOne(target.file)
    }
  }

  async function handleStarter(text: string) {
    // Empty-hero starters submit through the unbound path so no project is
    // minted server-side. The legacy `p_unset` mint is intentionally avoided.
    await send(selectedSlug ?? UNBOUND_SLUG, text)
  }

  /** Promote the current unbound chat to a project. Hands the typed name to
   *  `POST /lab/chats/{cid}/promote`; on success the URL flips to
   *  `/p/<slug>` via the App.tsx sync effect once `selectedSlug` lands. */
  async function handlePromote(name: string): Promise<void> {
    const cid = chatId
    if (!cid) return
    try {
      const { slug } = await promoteChat(cid, { name })
      // Order matters: refresh the projects list FIRST so the sidebar has the
      // new entry when select() flips selectedSlug (otherwise FSSpine paints
      // an "unknown slug" row for one frame). enterProject is then driven by
      // ChatPanel's effect and the adopt branch — events stay in place.
      await useProjects.getState().refresh()
      useProjects.getState().select(slug)
    } catch (err) {
      // Surface as a chat error event so the user sees the failure inline.
      const msg = err instanceof Error ? err.message : String(err)
      useChat.setState(s => ({
        events: [...s.events, {
          type: 'error',
          error_code: 'promote_failed',
          error_message_en: msg,
        }],
      }))
    }
  }

  return (
    <>
      {!compact && (
        <ConvHeader
          activeProject={selectedSlug ? projectName : ''}
          scope={selectedSlug ? 'project' : 'unbound'}
          currentChatId={chatId}
          chats={chats}
          onNew={() => {
            if (selectedSlug) {
              useChat.getState().newChat(selectedSlug)
              return
            }
            // Unbound: on `/c/<cid>` click "new chat" mints a fresh local id
            // and URL flips to `/c/<new_cid>` via the App.tsx sync effect.
            // On `/` the user is already on an empty slate — minting + flipping
            // would jump them off `/` for no benefit, so we no-op. Matches the
            // lazy pattern from the plan: first user message is what creates
            // the chat server-side.
            if (loadedUnboundChatId) {
              useChat.getState().newUnboundChat()
            }
          }}
          onSwitch={(cid) => {
            if (selectedSlug) {
              useChat.getState().switchChat(selectedSlug, cid)
            } else {
              useChat.getState().enterUnboundChat(cid)
            }
          }}
          onOpen={() => {
            if (selectedSlug) {
              void useChat.getState().listChats(selectedSlug)
            } else {
              void useChat.getState().listUnbound()
            }
          }}
        />
      )}
      {improveJob && (
        <ImproveBanner job={improveJob} onOpen={handleBannerOpen} />
      )}
      {hasContent ? (
        <div className="conv-scroll" ref={convScrollRef}>
          <div className="conv-inner">
            <ChatErrorBoundary key={`${selectedSlug ?? UNBOUND_SLUG}:${chatId}`}>
              <MessageList events={events} busy={busy} />
            </ChatErrorBoundary>
          </div>
        </div>
      ) : compact ? (
        <div className="chat-compact-empty" role="status">
          <span>{t('composer.placeholder.askField')}</span>
        </div>
      ) : (
        <EmptyHero
          projectName={projectName}
          onAttach={(files: File[]) => { void attach(files) }}
          onStarter={(text) => { void handleStarter(text) }}
        />
      )}
      <Composer
        disabled={busy && !pendingAskUser}
        pending={pending.map(p => ({ filename: p.filename, status: p.status, error: p.error }))}
        focusOnMount={!compact}
        projectId={selectedSlug ?? undefined}
        unbound={!selectedSlug}
        onPromote={isUnbound ? handlePromote : undefined}
        placeholder={composerPlaceholder}
        onAttach={(files: File[]) => { void attach(files) }}
        onRemove={(i) => setPending(p => p.filter((_, idx) => idx !== i))}
        onRetry={(i) => { void retry(i) }}
        onSubmit={async (text) => {
          // Only carry attachments that landed somewhere the backend can act on.
          // Failed/in-flight chips are filtered — the chip stays visible so the
          // user knows it didn't go, but the chat turn doesn't reference it.
          // Filename is the only doc handle; stage_token is the timing-shift
          // bridge for pre-pid drops (chat_turn claims + rewrites to filename
          // on the backend before persisting the user event).
          const ready = pending
            .filter(p => p.status === 'uploaded' || p.status === 'staged')
            .map(p => ({
              filename: p.filename,
              source: 'chat' as const,
              ...(p.stage_token ? { stage_token: p.stage_token } : {}),
            }))
          // In compact mode we are rendered inside the review overlay's chat
          // column OR inside the EvalMatrix drilldown's inline composer —
          // snapshot the active surface state BEFORE awaiting send so the
          // agent's tool calls bind to what the user was looking at when
          // they hit Enter, not to whatever they navigate to mid-response.
          // Reading via `getState()` here (rather than hook-derived values)
          // is intentional — the hook would have closed over render-time
          // state.
          //
          // Priority: eval_cell drilldown wins over review. When the user has
          // a drilldown open they are specifically looking at one cell; the
          // review surface may also be populated underneath, but the cell is
          // the more specific anchor for "why is this prediction wrong?"
          // style questions.
          let surfaceContext: SurfaceContext | undefined
          if (compact) {
            const ev = useEvalSurface.getState()
            if (ev.activeCell && ev.activeTs) {
              const c = ev.activeCell
              surfaceContext = {
                surface: 'eval_cell',
                filename: c.filename,
                field: c.field,
                eval_ts: ev.activeTs,
                truth: c.truth,
                pred: c.pred,
                status: c.status,
                verdict_reason: c.judge_reason ?? null,
                entity_idx: c.entity_idx,
              }
            } else {
              const rev = useReview.getState()
              if (rev.activeFilename) {
                const idx = rev.activeEntityIdx ?? 0
                const entity = rev.entities[idx] ?? {}
                const currentValue = rev.activeField
                  ? (entity as Record<string, unknown>)[rev.activeField] ?? null
                  : null
                const tabKey = rev.activeTabKey
                surfaceContext = {
                  surface: 'review',
                  filename: rev.activeFilename,
                  field: rev.activeField ?? null,
                  current_value: currentValue,
                  entity_index: idx,
                  page: rev.page,
                  page_count: rev.pageCount,
                  entity_count: rev.entities.length,
                  active_tab_key: tabKey,
                  experiment_id: tabKey && tabKey !== 'active' ? tabKey : null,
                }
              }
            }
          }
          await send(selectedSlug ?? UNBOUND_SLUG, text, ready, surfaceContext)
          setPending([])
        }}
        onCancel={() => useChat.getState().cancel()}
      />
    </>
  )
}
