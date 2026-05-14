import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface Props { text: string }

export default function AgentMessage({ text }: Props) {
  const [copied, setCopied] = useState(false)

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
              return isBlock ? (
                <code className={`${className ?? ''} font-mono`}>{children}</code>
              ) : (
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
      <div className="msg-actions" role="group" aria-label="Message actions">
        <button
          type="button"
          onClick={() => void copy()}
          title={copied ? 'Copied' : 'Copy'}
          aria-label="Copy"
          className={copied ? 'copied' : undefined}
        >
          {copied ? <Check size={16} aria-hidden /> : <Copy size={16} aria-hidden />}
        </button>
      </div>
    </div>
  )
}
