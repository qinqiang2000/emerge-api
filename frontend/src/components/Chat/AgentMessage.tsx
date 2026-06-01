import { useMemo, useState } from 'react'
import { Check, Copy } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { useT } from '../../i18n'
import { useProjects } from '../../stores/projects'
import { useDocs } from '../../stores/docs'
import { navigateToReview } from '../../lib/slugUrl'

interface Props { text: string }

export default function AgentMessage({ text }: Props) {
  const t = useT()
  const [copied, setCopied] = useState(false)

  // Make inline-code chips that name a real doc in this project clickable —
  // same destination as clicking the left-spine doc row (`navigateToReview`).
  // We match the chip's exact text against the project's doc list so only true
  // filenames become clickable; model ids / paths (`gemini-3-flash-preview`,
  // `predictions/_draft/`) stay inert plain chips. Unbound chats (no slug) have
  // an empty set, so everything degrades to plain chips. `original_name` is a
  // secondary key for the case where the agent shows the pre-dedupe name, but
  // navigation always uses the canonical on-disk `filename`.
  const selectedSlug = useProjects(s => s.selectedSlug)
  // Select the raw stored array (or undefined) — DON'T `?? []` inside the
  // selector: an empty-array literal is a fresh reference every render, which
  // trips useSyncExternalStore's cached-snapshot contract and infinite-loops
  // ("Maximum update depth exceeded"). This fires for new/empty projects and
  // unbound chats where docs were never loaded (`byProject[slug]` undefined).
  // Coalesce in the useMemo instead — same pattern as TaskChecklist.
  const docs = useDocs(s => (selectedSlug ? s.byProject[selectedSlug] : undefined))
  const docNames = useMemo(() => {
    const m = new Map<string, string>()
    for (const d of docs ?? []) {
      m.set(d.filename, d.filename)
      if (d.original_name && !m.has(d.original_name)) m.set(d.original_name, d.filename)
    }
    return m
  }, [docs])

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 800)
    } catch (err) {
      console.warn('copy failed', err)
    }
  }

  return (
    <div className="amsg w-full">
      <div className="msg text-ink leading-relaxed font-serif max-w-none">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          skipHtml
          components={{
            img: () => null,
            a: ({ href, children, ...rest }) => (
              <a
                {...rest}
                href={href}
                target="_blank"
                rel="noreferrer noopener"
                className="text-ochre-2 underline"
              >
                {children}
              </a>
            ),
            code: ({ className, children, ...rest }) => {
              const node = (rest as { node?: { position?: { start?: { column?: number } } } }).node
              const isBlock = node?.position?.start?.column === 1
              if (isBlock) {
                return <code className={`${className ?? ''} font-mono`}>{children}</code>
              }
              const raw = typeof children === 'string'
                ? children
                : Array.isArray(children) ? children.join('') : ''
              const filename = selectedSlug ? docNames.get(raw.trim()) : undefined
              if (filename) {
                const open = () => navigateToReview(selectedSlug!, filename)
                return (
                  <code
                    role="button"
                    tabIndex={0}
                    title={filename}
                    onClick={open}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open() } }}
                    className="font-mono bg-paper-2 border border-rule-soft text-ochre-2 px-1 py-0.5 rounded text-[0.86em] cursor-pointer hover:bg-ochre/10 hover:border-ochre transition-colors"
                  >
                    {children}
                  </code>
                )
              }
              return (
                <code className="font-mono bg-paper-2 border border-rule-soft text-ochre-2 px-1 py-0.5 rounded text-[0.86em]">
                  {children}
                </code>
              )
            },
            pre: ({ children }) => (
              <pre className="bg-paper-2 text-ink border border-rule p-3 rounded overflow-x-auto text-sm">
                {children}
              </pre>
            ),
            h1: ({ children }) => <h1 className="font-serif text-xl mt-3 mb-2">{children}</h1>,
            h2: ({ children }) => <h2 className="font-serif text-lg mt-3 mb-2">{children}</h2>,
            h3: ({ children }) => <h3 className="font-serif text-base mt-2 mb-1.5">{children}</h3>,
            table: ({ children }) => (
              <div className="overflow-x-auto my-2">
                <table className="border-collapse text-sm">{children}</table>
              </div>
            ),
            th: ({ children }) => (
              <th className="border border-rule px-2 py-1 text-left font-serif">{children}</th>
            ),
            td: ({ children }) => (
              <td className="border border-rule px-2 py-1">{children}</td>
            ),
            ul: ({ children }) => <ul className="list-disc ml-5 my-1.5 space-y-0.5">{children}</ul>,
            ol: ({ children }) => <ol className="list-decimal ml-5 my-1.5 space-y-0.5">{children}</ol>,
            p: ({ children }) => <p className="my-1.5">{children}</p>,
          }}
        >
          {text}
        </ReactMarkdown>
      </div>
      <div className="msg-actions" role="group" aria-label={t('msg.actions.aria')}>
        <button
          type="button"
          onClick={() => void copy()}
          title={copied ? t('msg.copied') : t('msg.copy')}
          aria-label={t('msg.copy')}
          className={copied ? 'copied' : undefined}
        >
          {copied ? <Check size={16} aria-hidden /> : <Copy size={16} aria-hidden />}
        </button>
      </div>
    </div>
  )
}
