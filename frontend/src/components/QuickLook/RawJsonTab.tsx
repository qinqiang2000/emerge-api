import { useEffect } from 'react'
import { useQuickLook } from '../../stores/quicklook'

export default function RawJsonTab() {
  const rawJson = useQuickLook(s => s.rawJson)
  const loadRaw = useQuickLook(s => s.loadRaw)
  const target = useQuickLook(s => s.target)

  useEffect(() => {
    if (!target) return
    if (rawJson.value === null && !rawJson.loading && !rawJson.error) {
      void loadRaw()
    }
  }, [target, rawJson.value, rawJson.loading, rawJson.error, loadRaw])

  if (rawJson.error) {
    return (
      <div className="ql-raw-error">
        {rawJson.error}
        <button type="button" className="ql-raw-retry" onClick={() => loadRaw()}>retry</button>
      </div>
    )
  }
  if (rawJson.loading || rawJson.value === null) {
    return <div className="ql-field-desc ql-field-desc--empty">loading…</div>
  }
  return (
    <div className="ql-raw-wrap">
      <button
        type="button"
        className="ql-raw-copy"
        onClick={() => navigator.clipboard?.writeText(rawJson.value ?? '')}
      >
        copy
      </button>
      <pre className="ql-raw">{rawJson.value}</pre>
    </div>
  )
}
