// frontend/src/components/Chat/SaveReviewedAdapter.tsx
//
// Hoisted-tool adapter for `save_reviewed`. Renders directly under the tool
// card (visually grouped) and offers chip-driven escalation:
//
//   * 升级到 description — converts the note into a schema description edit
//     by triggering a new chat turn with a feedback prompt bound to the same
//     (slug, filename, field) as the saved note.
//   * 升级到 global_notes — same but routes to project-wide notes.
//   * 忽略 — local-only dismiss (UI state); no agent call.
//
// The chip click derives its scope from the tool_call's own `tool_input`
// (the slug + filename + the single field key from `notes`). This keeps the
// escalation bound to the saved doc/field even if the user has since
// navigated to a different doc.

import { useState } from 'react'
import { useShallow } from 'zustand/react/shallow'

import { useChat, type SurfaceContext } from '../../stores/chat'
import { t as tImperative, useT } from '../../i18n'
import type { ChatEvent } from '../../types/chat'

type ToolCallEvent = Extract<ChatEvent, { type: 'tool_call' }>

interface Props { call: ToolCallEvent }

function _extractScope(call: ToolCallEvent): {
  slug: string | null
  filename: string | null
  field: string | null
  noteText: string | null
} {
  const input = (call.tool_input ?? {}) as Record<string, unknown>
  const slug = typeof input.slug === 'string' ? input.slug : null
  const filename = typeof input.filename === 'string' ? input.filename : null
  const notes = (input.notes && typeof input.notes === 'object')
    ? input.notes as Record<string, unknown>
    : null
  // Single-field note is the common case (Behavior hint intent class). Multi-
  // field would still escalate the first key; the UX assumes per-turn one
  // note. Field is sorted alphabetically so the choice is deterministic.
  const fieldKeys = notes ? Object.keys(notes).sort() : []
  const field = fieldKeys[0] ?? null
  const noteText = field && notes ? String(notes[field] ?? '') : null
  return { slug, filename, field, noteText }
}

function _surfaceContext(filename: string | null, field: string | null): SurfaceContext | undefined {
  if (!filename) return undefined
  return {
    surface: 'review',
    filename,
    field: field ?? null,
    // Escalation prompts don't need a current value — they're talking about
    // the description / global_notes, not a per-doc value. Entity index 0
    // is the safe default.
    current_value: null,
    entity_index: 0,
  }
}

export default function SaveReviewedAdapter({ call }: Props) {
  const t = useT()
  const [dismissed, setDismissed] = useState(false)
  const send = useChat(useShallow(s => s.send))

  const { slug, filename, field, noteText } = _extractScope(call)

  if (dismissed) return null
  // Only render the escalation chips when we have a clean (slug, filename,
  // field) triple — otherwise the chip can't bind to anything actionable.
  if (!slug || !filename || !field) return null

  const ctx = _surfaceContext(filename, field)

  function escalateToDescription() {
    if (!slug || !field) return
    const hint = noteText ? tImperative('saveReviewed.prompt.hint', { note: noteText }) : ''
    void send(
      slug,
      tImperative('saveReviewed.prompt.toDescription', { field, hint }),
      undefined,
      ctx,
    )
    setDismissed(true)
  }

  function escalateToGlobalNotes() {
    if (!slug || !field) return
    const hint = noteText ? tImperative('saveReviewed.prompt.hint', { note: noteText }) : ''
    void send(
      slug,
      tImperative('saveReviewed.prompt.toGlobal', { field, hint }),
      undefined,
      ctx,
    )
    setDismissed(true)
  }

  return (
    <div className="rev-chat-chips" data-testid="save-reviewed-adapter">
      <span className="rev-chat-chips-badge" title={t('saveReviewed.badge.title', { field, filename })}>
        {t('saveReviewed.noted.prefix')}<code>{field}</code>{t('saveReviewed.noted.of')}<code>{filename}</code>
      </span>
      <button
        type="button"
        className="rev-chat-chip"
        onClick={escalateToDescription}
        aria-label={t('saveReviewed.toDescription.aria')}
      >
        {t('saveReviewed.toDescription')}
      </button>
      <button
        type="button"
        className="rev-chat-chip"
        onClick={escalateToGlobalNotes}
        aria-label={t('saveReviewed.toGlobal.aria')}
      >
        {t('saveReviewed.toGlobal')}
      </button>
      <button
        type="button"
        className="rev-chat-chip rev-chat-chip-muted"
        onClick={() => setDismissed(true)}
        aria-label={t('saveReviewed.dismiss.aria')}
      >
        {t('saveReviewed.dismiss')}
      </button>
    </div>
  )
}
