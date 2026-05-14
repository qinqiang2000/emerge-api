import { create } from 'zustand'

export type QuickLookTarget =
  | { kind: 'schema'; pid: string }
  | { kind: 'version'; pid: string; versionId: string }
  | { kind: 'prompt'; pid: string; promptId: string }

interface RawJsonSlot {
  value: string | null
  loading: boolean
  error: string | null
}

interface QuickLookState {
  target: QuickLookTarget | null
  rawJson: RawJsonSlot

  openSchema: (pid: string) => void
  openVersion: (pid: string, versionId: string) => void
  openPrompt: (pid: string, promptId: string) => void
  close: () => void
  loadRaw: () => Promise<void>
}

const EMPTY_RAW: RawJsonSlot = { value: null, loading: false, error: null }

export const useQuickLook = create<QuickLookState>((set, get) => ({
  target: null,
  rawJson: EMPTY_RAW,

  openSchema: pid => set({ target: { kind: 'schema', pid }, rawJson: EMPTY_RAW }),
  openVersion: (pid, versionId) =>
    set({ target: { kind: 'version', pid, versionId }, rawJson: EMPTY_RAW }),
  openPrompt: (pid, promptId) =>
    set({ target: { kind: 'prompt', pid, promptId }, rawJson: EMPTY_RAW }),
  close: () => set({ target: null, rawJson: EMPTY_RAW }),

  loadRaw: async () => {
    const t = get().target
    if (!t) return
    set({ rawJson: { value: null, loading: true, error: null } })
    // For schema (= active prompt) and frozen version we have dedicated
    // pretty-printed text/plain endpoints. For a specific prompt variant we
    // fetch the JSON object and pretty-print it client-side — keeps the
    // backend surface small.
    // `t.pid` is a project slug post-transparency rename. The field name is
    // historical — keeping it avoids cascading test-fixture rewrites.
    const slug = encodeURIComponent(t.pid)
    const fetchText = async (): Promise<string> => {
      if (t.kind === 'schema') {
        const resp = await fetch(`/lab/projects/${slug}/schema/raw`)
        if (!resp.ok) throw resp
        return resp.text()
      }
      if (t.kind === 'version') {
        const resp = await fetch(`/lab/projects/${slug}/versions/${t.versionId}/raw`)
        if (!resp.ok) throw resp
        return resp.text()
      }
      const resp = await fetch(`/lab/projects/${slug}/prompts/${t.promptId}`)
      if (!resp.ok) throw resp
      const blob = await resp.json()
      return JSON.stringify(blob, null, 2)
    }

    try {
      const text = await fetchText()
      if (get().target !== t) return
      set({ rawJson: { value: text, loading: false, error: null } })
    } catch (e) {
      if (get().target !== t) return
      if (e instanceof Response) {
        let code = `http_${e.status}`
        try {
          const j = await e.json()
          code = j?.detail?.error_code ?? code
        } catch { /* not json */ }
        set({ rawJson: { value: null, loading: false, error: code } })
        return
      }
      set({ rawJson: { value: null, loading: false, error: (e as Error).message ?? 'fetch_failed' } })
    }
  },
}))
