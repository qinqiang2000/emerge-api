import { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, CornerDownLeft, MessageSquare } from 'lucide-react'

import { useChat } from '../../stores/chat'
import { useT } from '../../i18n'
import type { AskUserRequestEvent } from '../../types/chat'

interface Props {
  event: AskUserRequestEvent
}

/** Structured user-question card. Mirrors Claude Code's AskUserQuestion UX:
 *  header chip + question text + clickable option list. Single-select
 *  resolves on click; multiSelect collects toggles then resolves on Submit.
 *  Keyboard 1/2/3/4 picks the Nth option of the first un-answered question
 *  for fast confirmation flows. Once resolved the card stays in the
 *  conversation log as a "you answered X" trail so history reads naturally.
 *
 *  Lifecycle is pending-only — a reload during the prompt drops the card
 *  and the agent's await releases via cancel_pending_ask_user. */
export default function AskUserCard({ event }: Props) {
  const t = useT()
  const resolveAskUser = useChat(s => s.resolveAskUser)
  const resolved = event.resolution

  // Multi-select toggle state, keyed by question_index. Only used when at
  // least one question has multiSelect=true; single-select questions resolve
  // immediately on click without touching this map.
  const [picked, setPicked] = useState<Record<number, Set<number>>>({})

  const hasMultiSelect = useMemo(
    () => event.questions.some(q => q.multiSelect),
    [event.questions],
  )

  const handleSingleSelect = useCallback(
    (questionIndex: number, optionIndex: number) => {
      if (resolved) return
      const q = event.questions[questionIndex]
      if (!q) return
      const opt = q.options[optionIndex]
      if (!opt) return
      // Single-select for one question; if there are sibling questions, fill
      // them with empty selected[] — the agent reads question_index to map.
      const answers = event.questions.map((_, qi) => ({
        question_index: qi,
        selected: qi === questionIndex
          ? [{ option_index: optionIndex, label: opt.label }]
          : [],
      }))
      void resolveAskUser(event.request_id, answers)
    },
    [event.questions, event.request_id, resolveAskUser, resolved],
  )

  const toggleMulti = useCallback(
    (questionIndex: number, optionIndex: number) => {
      setPicked(prev => {
        const cur = new Set(prev[questionIndex] ?? [])
        if (cur.has(optionIndex)) cur.delete(optionIndex)
        else cur.add(optionIndex)
        return { ...prev, [questionIndex]: cur }
      })
    },
    [],
  )

  const handleSubmit = useCallback(() => {
    if (resolved) return
    const answers = event.questions.map((q, qi) => {
      const sel = picked[qi] ?? new Set<number>()
      const selectedArr = Array.from(sel).sort((a, b) => a - b).map(oi => ({
        option_index: oi,
        label: q.options[oi]?.label ?? '',
      }))
      return { question_index: qi, selected: selectedArr }
    })
    void resolveAskUser(event.request_id, answers)
  }, [event.questions, event.request_id, picked, resolveAskUser, resolved])

  // Keyboard 1-4 → pick the Nth option of the first single-select question
  // that isn't answered yet. Skip when there are multiSelect questions in
  // play (ambiguous: which question does the digit target?) — multi-select
  // requires explicit Submit, which keeps the kbd contract honest.
  useEffect(() => {
    if (resolved) return
    if (hasMultiSelect) return
    const firstQ = event.questions[0]
    if (!firstQ) return
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const tag = (e.target as HTMLElement | null)?.tagName?.toLowerCase()
      if (tag === 'input' || tag === 'textarea' || (e.target as HTMLElement | null)?.isContentEditable) {
        return
      }
      const n = Number(e.key)
      if (!Number.isInteger(n) || n < 1 || n > firstQ.options.length) return
      e.preventDefault()
      handleSingleSelect(0, n - 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [event.questions, handleSingleSelect, hasMultiSelect, resolved])

  // Resolved trail — keep the question visible but render the user's
  // answer instead of clickable options, so history reads naturally.
  // ``cancelled`` resolutions read as "I went a different direction" — the
  // glyph and label differ so the user can tell at a glance whether the
  // historical card was answered or redirected.
  if (resolved) {
    const cancelled = resolved.cancelled === true
    return (
      <div
        className="border-l-2 border-rule-soft bg-paper-2 px-3 py-2 flex flex-col gap-1.5"
        data-testid="ask-user-card-resolved"
      >
        {event.questions.map((q, qi) => {
          const ans = resolved.answers.find(a => a.question_index === qi)
          const labels = ans?.selected.map(s => s.label).join(', ')
          return (
            <div key={qi} className="flex items-baseline gap-2 font-mono text-sm">
              {cancelled
                ? <CornerDownLeft size={14} className="text-ink-3 self-center" />
                : <Check size={14} className="text-moss self-center" />}
              {q.header && (
                <span className="text-ink-4">[{q.header}]</span>
              )}
              <span className="text-ink-3 truncate min-w-0">{q.question}</span>
              <span className="text-ink-4">→</span>
              <span className={cancelled ? 'text-ink-3 italic' : 'text-ink'}>
                {cancelled ? t('ask.redirected') : (labels || t('ask.noAnswer'))}
              </span>
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <div
      className="border border-ochre-edge bg-ochre-soft rounded-lg px-3 py-3 flex flex-col gap-3"
      role="dialog"
      aria-label={t('ask.aria')}
      data-testid="ask-user-card"
    >
      <div className="flex items-baseline gap-2">
        <MessageSquare size={14} className="text-ochre-2 self-center" />
        <span className="font-mono text-xs uppercase tracking-wider text-ochre-2">
          {t('ask.questionLabel')}
        </span>
        {hasMultiSelect && (
          <span className="font-mono text-[10.5px] text-ink-4">{t('ask.multiSelectHint')}</span>
        )}
      </div>

      {event.questions.map((q, qi) => (
        <div key={qi} className="flex flex-col gap-2">
          <div className="flex items-baseline gap-2 flex-wrap">
            {q.header && (
              <span className="font-mono text-[10.5px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-paper text-ochre-2 border border-ochre-edge">
                {q.header}
              </span>
            )}
            <span className="font-sans text-[13.5px] text-ink leading-snug">
              {q.question}
            </span>
          </div>
          <ul className="flex flex-col gap-1.5">
            {q.options.map((opt, oi) => {
              const isPicked = picked[qi]?.has(oi) ?? false
              const showHotkey = !hasMultiSelect && qi === 0 && oi < 9
              return (
                <li key={oi}>
                  <button
                    type="button"
                    onClick={() => q.multiSelect ? toggleMulti(qi, oi) : handleSingleSelect(qi, oi)}
                    className={
                      'w-full text-left flex items-start gap-2 px-2.5 py-1.5 rounded border transition-colors ' +
                      (isPicked
                        ? 'border-ochre bg-paper'
                        : 'border-rule-soft bg-paper hover:border-ochre hover:bg-ochre-soft')
                    }
                  >
                    <span
                      className="font-mono text-[11px] text-ink-4 mt-[2px] tabular-nums"
                      aria-hidden="true"
                    >
                      {showHotkey ? `${oi + 1}` : `${oi + 1}.`}
                    </span>
                    <span className="flex flex-col gap-0.5 min-w-0 flex-1">
                      <span className="font-sans text-[13px] text-ink">
                        {opt.label}
                        {q.multiSelect && isPicked && (
                          <Check size={12} className="text-moss inline-block ml-1.5 -mt-0.5" />
                        )}
                      </span>
                      {opt.description && (
                        <span className="font-sans text-[12px] text-ink-3 leading-snug">
                          {opt.description}
                        </span>
                      )}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      ))}

      {hasMultiSelect && (
        <div className="flex">
          <button
            type="button"
            onClick={handleSubmit}
            className="font-mono text-xs px-3 py-1.5 rounded border border-ochre bg-paper text-ochre-2 hover:bg-ochre-soft transition-colors"
          >
            {t('ask.submit')}
          </button>
        </div>
      )}

      {/* Universal escape hint: typing in the composer redirects/cancels any
          pending ask_user (see chat store mid-prompt redirect). Surfaced here
          so the option list never needs a per-question "cancel" entry. */}
      <span className="font-sans text-[11.5px] text-ink-4 leading-snug">
        {t('ask.redirectHint')}
      </span>
    </div>
  )
}
