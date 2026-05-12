// frontend/src/components/ReviewMode/JsonView.tsx
// T11.6 — JSON view with line numbers and per-key highlighting on activeField.
// Builds JSON from entities[entityIdx] directly (no sub-shape required).

interface Props {
  data: Record<string, unknown>
  activeField: string | null
  readOnly?: boolean
}

interface JsonLine {
  lineNo: number
  text: string
  key: string | null  // field key if this line contains one
}

function buildLines(data: Record<string, unknown>): JsonLine[] {
  const jsonStr = JSON.stringify(data, null, 2)
  const rawLines = jsonStr.split('\n')
  // Regex to detect lines like:  "key": value
  const keyRe = /^\s+"([^"]+)":/
  return rawLines.map((text, i) => {
    const m = text.match(keyRe)
    return { lineNo: i + 1, text, key: m ? m[1] : null }
  })
}

function colorizeText(text: string): React.ReactNode {
  // Very lightweight syntax highlight — string values, numbers, booleans
  // We apply color via className spans on token groups
  const parts: React.ReactNode[] = []
  let remaining = text

  // Pattern: "key": value
  const kvRe = /^(\s*)("(?:[^"\\]|\\.)*")(:\s*)(.*)/
  const m = remaining.match(kvRe)
  if (m) {
    // key part
    if (m[1]) parts.push(m[1])
    parts.push(<span key="k" className="jk">{m[2]}</span>)
    parts.push(m[3])
    remaining = m[4]
  }

  // value coloring
  if (/^"/.test(remaining)) {
    parts.push(<span key="v" className="js">{remaining}</span>)
  } else if (/^-?\d/.test(remaining)) {
    parts.push(<span key="v" className="jn">{remaining}</span>)
  } else if (/^(true|false)/.test(remaining)) {
    parts.push(<span key="v" className="jb">{remaining}</span>)
  } else {
    parts.push(remaining)
  }

  return <>{parts}</>
}

export default function JsonView({ data, activeField, readOnly: _readOnly }: Props) {
  const lines = buildLines(data)

  return (
    <div className="rev-json">
      <pre>
        {lines.map((line) => {
          const isActive = activeField !== null && line.key === activeField
          return (
            <div key={line.lineNo} className={`jl${isActive ? ' rowhi' : ''}`}>
              <span className="ln">{String(line.lineNo).padStart(3, ' ')}</span>
              <span className="jc">
                {isActive && line.key
                  ? colorizeLineWithActiveKey(line.text, line.key)
                  : colorizeText(line.text)
                }
              </span>
            </div>
          )
        })}
      </pre>
    </div>
  )
}

function colorizeLineWithActiveKey(text: string, _key: string): React.ReactNode {
  // Same as colorizeText but mark the key span with .active
  const parts: React.ReactNode[] = []
  let remaining = text

  const kvRe = /^(\s*)("(?:[^"\\]|\\.)*")(:\s*)(.*)/
  const m = remaining.match(kvRe)
  if (m) {
    if (m[1]) parts.push(m[1])
    parts.push(<span key="k" className="jk active">{m[2]}</span>)
    parts.push(m[3])
    remaining = m[4]
  }

  if (/^"/.test(remaining)) {
    parts.push(<span key="v" className="js">{remaining}</span>)
  } else if (/^-?\d/.test(remaining)) {
    parts.push(<span key="v" className="jn">{remaining}</span>)
  } else if (/^(true|false)/.test(remaining)) {
    parts.push(<span key="v" className="jb">{remaining}</span>)
  } else {
    parts.push(remaining)
  }

  return <>{parts}</>
}
