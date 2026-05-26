// Transport wrapper for M11's turn-as-resource surface.
//
// The backend split the agent loop from the SSE request lifetime in M11:
// `POST /lab/chats/{cid}/turns` starts a long-lived turn, `GET .../stream`
// is a tail-f subscription, `POST .../cancel` is explicit kill, and
// `GET .../turn_state` lets a re-entering client decide whether to attach
// or treat the chat as static history. This module is a thin transport
// layer over those four endpoints — no store coupling, no UI strings.
//
// Why a separate file (vs growing `api.ts`): the chat store (T5) imports
// these four helpers as a unit when refactoring `send` into `startTurn +
// attachStream`. Keeping the turn surface in one file makes the cutover
// reviewable as a single diff and lets the mock layer in `chat.test.ts`
// target a stable import path.

import { streamSSE, type SSEEvent } from './sse'
import type { SurfaceContext } from '../stores/chat'

const API = '' // same-origin via vite proxy; mirrors api.ts

/** Mirror of backend ``StartTurnBody``. ``slug`` is the chat's destination
 *  ownership handle: a real project slug, the ``_chats`` sentinel for an
 *  unbound chat, or ``p_unset`` for the legacy empty-hero auto-mint path.
 *  Backend ``ChatService.chat_turn`` keeps its pre-M11 signature, so the
 *  body shape on the wire is identical for committed / unbound flows. */
export interface StartTurnBody {
  slug: string
  user_message: string
  attachments?: Array<{
    filename?: string
    stage_token?: string
    source?: 'chat' | 'docs'
    /** Backend-classified kind from staging/attach response — agent uses it
     *  to route the file (doc → docs/, schema → ask before importing, etc.).
     *  Optional: legacy backends omit it; agent falls back to the doc default. */
    kind?: 'doc' | 'schema' | 'data' | 'note'
  }>
  surface_context?: SurfaceContext
}

export type TurnStatus = 'running' | 'done' | 'cancelled' | 'error'

export interface StartTurnResponse {
  turn_id: string
  status: TurnStatus
}

/** Shape of ``GET /lab/chats/{cid}/turn_state``. ``active_turn_id`` /
 *  ``status`` are ``null`` when no live turn is registered for the chat;
 *  ``last_offset`` still reports the events.jsonl line count in that
 *  case so a cold reload can hydrate without first attaching to a stream. */
export interface TurnState {
  active_turn_id: string | null
  status: TurnStatus | null
  last_offset: number
}

function chatTurnsUrl(cid: string): string {
  return `${API}/lab/chats/${encodeURIComponent(cid)}/turns`
}

/** Lift the backend ``{error_code, error_message_en}`` envelope out of a
 *  non-2xx response and throw it as an ``Error`` whose message contains
 *  the code. Mirrors the implicit pattern in ``api.ts`` (``attachToChat``,
 *  ``stageUpload``, ``promoteChat``) which try to pull ``detail`` out of
 *  the body before falling back to ``<op> <status>``. We accept either
 *  ``{error_code, error_message_en}`` (M11 routes) or ``{detail: {...}}``
 *  (existing FastAPI HTTPException wrapping) so the helper works against
 *  both surfaces during the cutover. Best-effort: any parse failure
 *  degrades to a status-coded message. */
async function throwEnvelope(op: string, r: Response): Promise<never> {
  let code = `http_${r.status}`
  let message = ''
  try {
    const body = await r.json() as {
      error_code?: string
      error_message_en?: string
      detail?: { error_code?: string; error_message_en?: string } | string
    }
    if (typeof body.error_code === 'string') {
      code = body.error_code
      message = body.error_message_en ?? ''
    } else if (body.detail && typeof body.detail === 'object') {
      if (typeof body.detail.error_code === 'string') code = body.detail.error_code
      if (typeof body.detail.error_message_en === 'string') message = body.detail.error_message_en
    } else if (typeof body.detail === 'string') {
      message = body.detail
    }
  } catch {
    /* swallow — fall through to status-coded error */
  }
  const tail = message ? `: ${message}` : ''
  throw new Error(`${op} ${code}${tail}`)
}

/** Kick off a chat turn. Returns the registry-assigned ``turn_id`` so the
 *  caller can attach a stream, persist the id under ``turn:{cid}`` for
 *  re-attach across reloads, and POST cancel on stop. Rejects with the
 *  raw envelope on 409 ``turn_already_active`` (and any other non-2xx). */
export async function startTurn(
  cid: string,
  body: StartTurnBody,
): Promise<StartTurnResponse> {
  const r = await fetch(chatTurnsUrl(cid), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) await throwEnvelope('startTurn', r)
  return r.json() as Promise<StartTurnResponse>
}

/** Subscribe to a turn's SSE stream. Thin wrapper over ``streamSSE`` that
 *  bakes in the ``after_offset`` query param and forces method GET.
 *
 *  ``streamSSE`` already accepts arbitrary ``RequestInit`` (see how
 *  ``jobs.ts`` passes ``method: 'GET'``), so no sse.ts extension is
 *  needed — this helper is purely URL-building + signal plumbing.
 *
 *  User-initiated aborts surface as ``AbortError`` from the underlying
 *  fetch. We rethrow unchanged so the caller can detect the abort the
 *  same way ``stores/jobs.ts`` does (``(e as Error).name === 'AbortError'``)
 *  and silently exit. Anything else propagates. */
export function attachStream(
  cid: string,
  tid: string,
  opts: { after_offset: number; signal: AbortSignal },
): AsyncIterable<SSEEvent> {
  const url =
    `${chatTurnsUrl(cid)}/${encodeURIComponent(tid)}/stream` +
    `?after_offset=${encodeURIComponent(String(opts.after_offset))}`
  return streamSSE(url, { method: 'GET', signal: opts.signal })
}

/** POST an explicit cancel for the given turn. Idempotent on the
 *  backend — an unknown ``tid`` returns ``{status: 'not_found'}`` with
 *  HTTP 200, so clients can fire-and-forget without a guard. Any
 *  non-2xx still raises (network / 5xx). */
export async function cancelTurn(
  cid: string,
  tid: string,
): Promise<{ status: TurnStatus | 'not_found' }> {
  const r = await fetch(
    `${chatTurnsUrl(cid)}/${encodeURIComponent(tid)}/cancel`,
    { method: 'POST' },
  )
  if (!r.ok) await throwEnvelope('cancelTurn', r)
  return r.json() as Promise<{ status: TurnStatus | 'not_found' }>
}

/** Read the chat's live turn state. Used by ``enterProject`` /
 *  ``enterUnboundChat`` / ``switchChat`` in T6 to decide whether to
 *  re-attach an existing stream or treat the chat as static history.
 *  Returns ``{active_turn_id: null, status: null, last_offset: N}``
 *  when no live turn is registered — ``last_offset`` is still the
 *  events.jsonl line count so a cold reload can hydrate cheaply. */
export async function fetchTurnState(cid: string): Promise<TurnState> {
  const r = await fetch(
    `${API}/lab/chats/${encodeURIComponent(cid)}/turn_state`,
  )
  if (!r.ok) await throwEnvelope('fetchTurnState', r)
  return r.json() as Promise<TurnState>
}
