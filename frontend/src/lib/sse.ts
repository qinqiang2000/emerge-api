export interface SSEEvent {
  event: string
  data: unknown
}

export async function* streamSSE(url: string, init: RequestInit): AsyncGenerator<SSEEvent> {
  const resp = await fetch(url, init)
  if (!resp.ok || !resp.body) throw new Error(`SSE ${resp.status}`)
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const block = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      const lines = block.split('\n')
      let event = 'message'
      let dataStr = ''
      for (const ln of lines) {
        if (ln.startsWith('event:')) event = ln.slice(6).trim()
        else if (ln.startsWith('data:')) dataStr = ln.slice(5).trim()
      }
      let data: unknown = dataStr
      try { data = JSON.parse(dataStr) } catch { /* keep string */ }
      yield { event, data }
    }
  }
}
