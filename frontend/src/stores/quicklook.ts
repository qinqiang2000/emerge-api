import { create } from 'zustand'
import { hoistGlobalNotes } from '../lib/promptJson'

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
  /**
   * True while the raw-json editor's buffer diverges from the persisted
   * active prompt. RawJsonTab toggles it so PromptQuickLook can append
   * the dirty dot to the "raw json" tab title without lifting buffer
   * state. Reset to false on every target change and on every save.
   */
  rawDirty: boolean
  /**
   * Sheet sizing preference. Persisted to localStorage so frequent editors
   * stay maximized across opens. Default size is the original 720px peek
   * card; maximized goes to ~96vw/96vh for serious editing.
   */
  maximized: boolean

  openPrompt: (pid: string, promptId?: string) => void
  openVersion: (pid: string, versionId: string) => void
  close: () => void
  setRawDirty: (dirty: boolean) => void
  toggleMaximized: () => void
  /**
   * Fetch the raw-json snapshot. Used by the version branch (frozen) and
   * by the variant branch (read-only via `promptId`). The active-prompt
   * branch now derives raw json from `usePrompts.activeByProject` so the
   * form and the editor share the same in-memory truth — no fetch here.
   */
  loadRaw: () => Promise<void>
}

const EMPTY_RAW: RawJsonSlot = { value: null, loading: false, error: null }

const MAXIMIZED_KEY = 'emerge.quicklook.maximized'
function readMaximized(): boolean {
  try {
    return typeof window !== 'undefined' && window.localStorage?.getItem(MAXIMIZED_KEY) === '1'
  } catch {
    return false
  }
}
function writeMaximized(v: boolean) {
  try {
    window.localStorage?.setItem(MAXIMIZED_KEY, v ? '1' : '0')
  } catch { /* SSR / privacy mode — ignore */ }
}

export const useQuickLook = create<QuickLookState>((set, get) => ({
  target: null,
  rawJson: EMPTY_RAW,
  rawDirty: false,
  maximized: readMaximized(),

  openPrompt: (pid, promptId) =>
    set({ target: { kind: 'prompt', pid, promptId }, rawJson: EMPTY_RAW, rawDirty: false }),
  openVersion: (pid, versionId) =>
    set({ target: { kind: 'version', pid, versionId }, rawJson: EMPTY_RAW, rawDirty: false }),
  close: () => set({ target: null, rawJson: EMPTY_RAW, rawDirty: false }),
  setRawDirty: (dirty) => set({ rawDirty: dirty }),
  toggleMaximized: () => {
    const next = !get().maximized
    writeMaximized(next)
    set({ maximized: next })
  },

  loadRaw: async () => {
    const t = get().target
    if (!t) return
    // The active prompt's raw view is now derived from `usePrompts` inside
    // RawJsonTab — no fetch here. Skip silently so existing call-sites stay
    // safe.
    if (t.kind === 'prompt' && !t.promptId) return
    set({ rawJson: { value: null, loading: true, error: null } })
    // Frozen versions have a dedicated text/plain pretty-printed endpoint.
    // Named variants return a PromptVariant blob; we pretty-print client-side
    // so global_notes and the schema array round-trip into the raw view
    // together. `t.pid` is a project slug post-transparency rename — the
    // field name is historical, kept to avoid cascading fixture rewrites.
    const slug = encodeURIComponent(t.pid)
    const fetchText = async (): Promise<string> => {
      if (t.kind === 'version') {
        const resp = await fetch(`/lab/projects/${slug}/versions/${t.versionId}/raw`)
        if (!resp.ok) throw resp
        const parsed = JSON.parse(await resp.text())
        return JSON.stringify(hoistGlobalNotes(parsed), null, 2)
      }
      // Variant prompt (read-only) — kind === 'prompt' && promptId set
      const resp = await fetch(`/lab/projects/${slug}/prompts/${t.promptId}`)
      if (!resp.ok) throw resp
      return JSON.stringify(hoistGlobalNotes(await resp.json()), null, 2)
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
