// frontend/src/components/Chat/ReviewBoardCard.tsx
//
// Chat card for `render_review_board`. Unlike AuditCard/EvalCard, this tool's
// text return is a plain-language narrative, NOT JSON — so there's no
// tool_result JSON to adapt. Instead the card, once it recognises a successful
// `render_review_board` call, pulls the board payload itself via the
// `useReviewBoard` store (cache-first, same self-pull posture as EvalCardAdapter
// receiving `slug` from MessageList). Strict: any other tool → null so the
// generic ToolCall rendering is never hijacked.
import { useEffect, useMemo } from 'react'

import type { ChatEvent } from '../../types/chat'
import { useT } from '../../i18n'
import { pathForReviewBoard } from '../../lib/slugUrl'
import { useProjects } from '../../stores/projects'
import { useReviewBoard } from '../../stores/reviewBoard'
import { toolShortHint } from '../../lib/toolHint'
import ToolCall from './ToolCall'
import ToolRow from './ToolRow'

const REVIEW_BOARD_TOOL = 'mcp__emerge_tools__render_review_board'

// Verdict → colored dot class (semantic tokens only; mirrors the overlay).
const VERDICT_DOT: Record<'pass' | 'fail' | 'unclear', string> = {
  pass: 'bg-moss',
  fail: 'bg-rose',
  unclear: 'bg-ink-4',
}

/** First sentence of a reason, truncated — keeps the row scannable. */
export function firstSentence(reason: string): string {
  const s = reason.split(/(?<=[。.!?！？])\s*/)[0] ?? reason
  return s.length > 60 ? s.slice(0, 60) + '…' : s
}

type ToolCallEvent = Extract<ChatEvent, { type: 'tool_call' }>

function ReviewBoardCard({ slug }: { slug: string }) {
  const t = useT()
  const entry = useReviewBoard(s => s.byProject[slug])
  const load = useReviewBoard(s => s.load)

  // Cache-first: only fetches if the store doesn't already hold this slug.
  useEffect(() => {
    void load(slug)
  }, [slug, load])

  // Coalesce in a memo (selector discipline — never `?? []` in the selector).
  const docs = useMemo(() => entry?.docs ?? [], [entry])

  const openBoard = () => {
    window.history.pushState(null, '', pathForReviewBoard(slug))
    window.dispatchEvent(new PopStateEvent('popstate'))
  }

  return (
    <div
      className="border border-rule-soft bg-paper rounded-sm font-mono text-sm"
      data-testid="review-board-card"
    >
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-rule-soft">
        <span className="text-ink font-semibold">{t('reviewboard.title')}</span>
        {entry && entry.tally.fail > 0 && (
          <span className="text-rose text-xs">
            {t('reviewboard.tally.fail', { n: entry.tally.fail })}
          </span>
        )}
        {entry && entry.tally.pass > 0 && (
          <span className="text-moss text-xs">
            {t('reviewboard.tally.pass', { n: entry.tally.pass })}
          </span>
        )}
        {entry?.model_label && (
          <span className="text-ink-4 text-xs">{entry.model_label}</span>
        )}
        <button
          type="button"
          data-testid="review-board-open"
          className="ml-auto text-xs px-2 py-0.5 rounded-sm border border-ochre-2 text-ochre-2 hover:bg-paper-2 font-semibold"
          title={t('reviewboard.open')}
          onClick={openBoard}
        >
          {t('reviewboard.open')} ↗
        </button>
      </div>
      <div>
        {docs.map(d => (
          <div
            key={d.id}
            className="px-3 py-1.5 border-b border-rule-soft last:border-b-0 flex items-start gap-2"
          >
            <span
              className={`shrink-0 mt-1.5 w-2 h-2 rounded-full ${VERDICT_DOT[d.verdict]}`}
              aria-hidden="true"
            />
            <span className="shrink-0 text-ink">{d.id}</span>
            {d.reason && (
              <span className="text-ink-4 min-w-0 break-words">{firstSentence(d.reason)}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export function ReviewBoardCardAdapter({ call }: { call: ToolCallEvent }) {
  const slug = useProjects(s => s.selectedSlug)
  const status = call.ok === false ? 'err' : call.tool_result == null ? 'run' : 'done'
  const displayName = call.tool_name.replace(/^mcp__emerge_tools__/, '')
  const hint = status !== 'run' ? toolShortHint(call.tool_name, call.tool_result) : null

  if (status === 'done' && slug) {
    return (
      <>
        <ToolCall name={displayName} args={hint ?? undefined} status={status}>
          <ToolRow glyph="·" label="input" value={JSON.stringify(call.tool_input)} />
        </ToolCall>
        <ReviewBoardCard slug={slug} />
      </>
    )
  }

  // Fallback: running / error / no project selected → plain ToolCall.
  return (
    <ToolCall name={displayName} args={hint ?? undefined} status={status}>
      <ToolRow glyph="·" label="input" value={JSON.stringify(call.tool_input)} />
      {call.tool_result != null && (
        <ToolRow
          glyph="↳"
          label="result"
          value={typeof call.tool_result === 'string' ? call.tool_result : JSON.stringify(call.tool_result, null, 2)}
        />
      )}
    </ToolCall>
  )
}

export { REVIEW_BOARD_TOOL }
