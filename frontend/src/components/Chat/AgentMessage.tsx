import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface Props { text: string }

export default function AgentMessage({ text }: Props) {
  return (
    <div className="text-fg-primary leading-relaxed font-body max-w-none">
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
              className="text-accent-primary underline"
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
              <code className="font-mono bg-subtle text-fg-primary px-1 py-0.5 rounded text-[0.9em]">
                {children}
              </code>
            )
          },
          pre: ({ children }) => (
            <pre className="bg-subtle text-fg-primary p-3 rounded overflow-x-auto text-sm">
              {children}
            </pre>
          ),
          h1: ({ children }) => <h1 className="font-heading text-xl mt-3 mb-2">{children}</h1>,
          h2: ({ children }) => <h2 className="font-heading text-lg mt-3 mb-2">{children}</h2>,
          h3: ({ children }) => <h3 className="font-heading text-base mt-2 mb-1.5">{children}</h3>,
          table: ({ children }) => (
            <div className="overflow-x-auto my-2">
              <table className="border-collapse text-sm">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-subtle px-2 py-1 text-left font-heading">{children}</th>
          ),
          td: ({ children }) => (
            <td className="border border-subtle px-2 py-1">{children}</td>
          ),
          ul: ({ children }) => <ul className="list-disc ml-5 my-1.5 space-y-0.5">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal ml-5 my-1.5 space-y-0.5">{children}</ol>,
          p: ({ children }) => <p className="my-1.5">{children}</p>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}
