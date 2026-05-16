import { create } from 'zustand'

export type QuickLookTarget =
  | { kind: 'prompt'; pid: string; promptId?: string }
  | { kind: 'version'; pid: string; versionId: string }

interface RawJsonSlot {
  value: string | null
  loading: boolean
  error: string | null
}

interface QuickLookState {
  target: QuickLookTarget | null
  rawJson: RawJsonSlot

  openPrompt: (pid: string, promptId?: string) => void
  openVersion: (pid: string, versionId: string) => void
  close: () => void
  loadRaw: () => Promise<void>
}

const EMPTY_RAW: RawJsonSlot = { value: null, loading: false, error: null }

export const useQuickLook = create<QuickLookState>((set, get) => ({
  target: null,
  rawJson: EMPTY_RAW,

  openPrompt: (pid, promptId) =>
    set({ target: { kind: 'prompt', pid, promptId }, rawJson: EMPTY_RAW }),
  openVersion: (pid, versionId) =>
    set({ target: { kind: 'version', pid, versionId }, rawJson: EMPTY_RAW }),
  close: () => set({ target: null, rawJson: EMPTY_RAW }),

  loadRaw: async () => {
    const t = get().target
    if (!t) return
    set({ rawJson: { value: null, loading: true, error: null } })
    // Frozen versions have a dedicated text/plain pretty-printed endpoint.
    // Both the active prompt (promptId undefined) and named variants return a
    // PromptVariant blob; we pretty-print client-side so global_notes and the
    // schema array round-trip into the raw view together.
    // `t.pid` is a project slug post-transparency rename. The field name is
    // historical — keeping it avoids cascading test-fixture rewrites.
    const slug = encodeURIComponent(t.pid)
    const fetchText = async (): Promise<string> => {
      if (t.kind === 'version') {
        const resp = await fetch(`/lab/projects/${slug}/versions/${t.versionId}/raw`)
        if (!resp.ok) throw resp
        return resp.text()
      }
      const url = t.promptId
        ? `/lab/projects/${slug}/prompts/${t.promptId}`
        : `/lab/projects/${slug}/prompts/active`
      const resp = await fetch(url)
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
