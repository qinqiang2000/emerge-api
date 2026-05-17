import { useEffect, useMemo, useRef, useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { json, jsonParseLinter } from '@codemirror/lang-json'
import { linter } from '@codemirror/lint'
import { EditorView, keymap } from '@codemirror/view'
import { useQuickLook } from '../../stores/quicklook'
import { usePrompts } from '../../stores/prompts'
import { useSchema } from '../../stores/schema'
import { Reminder } from '../Reminder'
import { parsePromptJson, serializePrompt } from '../../lib/promptJson'

/**
 * CodeMirror theme that maps editor chrome onto our CSS-var tokens.
 * Tailwind colors are forbidden in the codebase, so all surfaces (gutter,
 * cursor, selection) reach for `var(--paper-*)` / `var(--ink-*)`. The
 * default `lang-json` syntax highlighting stays — it ships its own light /
 * dark heuristics that work well against either palette.
 */
const editorTheme = EditorView.theme({
  '&': {
    height: '100%',
    backgroundColor: 'var(--paper-2)',
    color: 'var(--ink)',
    fontFamily: 'var(--mono, ui-monospace, monospace)',
    fontSize: '12px',
  },
  '.cm-scroller': {
    fontFamily: 'inherit',
    lineHeight: '1.55',
  },
  '.cm-gutters': {
    backgroundColor: 'var(--paper-2)',
    color: 'var(--ink-5)',
    border: 'none',
  },
  '.cm-activeLine': { backgroundColor: 'transparent' },
  '.cm-activeLineGutter': { backgroundColor: 'transparent' },
  '.cm-cursor': { borderLeftColor: 'var(--ink)' },
  '.cm-selectionBackground, &.cm-focused .cm-selectionBackground, ::selection': {
    backgroundColor: 'var(--ochre-soft)',
  },
})

export default function RawJsonTab() {
  const target = useQuickLook(s => s.target)

  if (!target) return null
  if (target.kind === 'prompt' && !target.promptId) {
    return <ActivePromptRawJson pid={target.pid} />
  }
  return <ReadOnlyRawJson />
}

function ActivePromptRawJson({ pid }: { pid: string }) {
  const activePrompt = usePrompts(s => s.activeByProject[pid])
  const loadPrompts = usePrompts(s => s.load)

  useEffect(() => {
    if (!activePrompt) void loadPrompts(pid)
  }, [pid, activePrompt, loadPrompts])

  const external = useMemo(
    () => (activePrompt ? serializePrompt(activePrompt) : ''),
    [activePrompt],
  )

  // Last-synced pattern (mirrored from NotesEditor): keep the local buffer,
  // but accept external value changes when the user hasn't diverged from
  // them. Means a successful save round-trips cleanly, and a NOTES edit in
  // the form propagates here when the buffer still matches the prior
  // serialization.
  const [buffer, setBuffer] = useState<string>(external)
  const lastSyncedRef = useRef<string>(external)
  useEffect(() => {
    if (buffer === lastSyncedRef.current || buffer === '') {
      setBuffer(external)
      lastSyncedRef.current = external
    } else {
      // External changed but user has unsaved local edits — leave buffer
      // alone. They'll see the dirty dot in the tab title.
      lastSyncedRef.current = external
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [external])

  const parseResult = useMemo(() => parsePromptJson(buffer), [buffer])
  const dirty = buffer !== external && external !== ''
  const [saveErr, setSaveErr] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // Surface dirty state to PromptQuickLook so it can append a dot to the
  // tab title. Store-backed instead of lifted state to keep the editor
  // self-contained.
  const setRawDirty = useQuickLook(s => s.setRawDirty)
  useEffect(() => {
    setRawDirty(dirty)
    return () => setRawDirty(false)
  }, [dirty, setRawDirty])

  const canSave = dirty && parseResult.ok && !saving

  const onSave = async () => {
    if (!canSave || !parseResult.ok) return
    setSaving(true)
    setSaveErr(null)
    const err = await useSchema
      .getState()
      .saveActive(pid, parseResult.value.schema, parseResult.value.global_notes)
    setSaving(false)
    if (err) {
      setSaveErr(err.error_code + (err.error_message_en ? `: ${err.error_message_en}` : ''))
      return
    }
    // Patch usePrompts so the form re-derives in sync — saveActive only
    // touches useSchema.byProject, but the form reads `global_notes` from
    // usePrompts.activeByProject. Mirrors NotesEditor's patch.
    usePrompts.setState((s) => {
      const cur = s.activeByProject[pid]
      if (!cur) return s
      return {
        activeByProject: {
          ...s.activeByProject,
          [pid]: {
            ...cur,
            schema: parseResult.value.schema,
            global_notes: parseResult.value.global_notes,
          },
        },
      }
    })
    // The external string is memoized off `activePrompt`. The setState above
    // triggers a re-render and `external` updates to the new serialization;
    // the last-synced effect then accepts the new external as the baseline,
    // clearing `dirty` (and hence the tab dot) automatically.
  }

  // ⌘S / Ctrl+S — keep the keymap stable across renders so CodeMirror
  // doesn't tear down the editor each save.
  const saveRef = useRef(onSave)
  saveRef.current = onSave
  const extensions = useMemo(
    () => [
      json(),
      linter(jsonParseLinter()),
      editorTheme,
      keymap.of([
        {
          key: 'Mod-s',
          preventDefault: true,
          run: () => {
            void saveRef.current()
            return true
          },
        },
      ]),
    ],
    [],
  )

  if (!activePrompt) {
    return <Reminder form="inline" intent="note">loading…</Reminder>
  }

  // Show codemirror lint errors implicitly (gutter underlines), plus a
  // single Reminder summarising parse / shape failure or save failure.
  const reminder = saveErr
    ? <Reminder intent="caution" title={saveErr} />
    : !parseResult.ok
      ? <Reminder intent="caution" title={parseResult.error} />
      : null

  return (
    <div className="ql-raw-wrap ql-raw-edit">
      {reminder && <div className="ql-raw-reminder">{reminder}</div>}
      <div className="ql-raw-editor">
        <div className="ql-raw-actions">
          <button
            type="button"
            className="ql-raw-copy"
            onClick={() => navigator.clipboard?.writeText(buffer)}
          >
            copy
          </button>
          <button
            type="button"
            className="ql-raw-save"
            onClick={() => { void onSave() }}
            disabled={!canSave}
            title="save (⌘S)"
          >
            {saving ? 'saving…' : 'save'}
          </button>
        </div>
        <CodeMirror
          value={buffer}
          height="100%"
          theme="light"
          extensions={extensions}
          onChange={(v) => setBuffer(v)}
          basicSetup={{ lineNumbers: true, foldGutter: false, highlightActiveLine: false }}
        />
      </div>
    </div>
  )
}

function ReadOnlyRawJson() {
  const rawJson = useQuickLook(s => s.rawJson)
  const loadRaw = useQuickLook(s => s.loadRaw)
  const target = useQuickLook(s => s.target)

  useEffect(() => {
    if (!target) return
    if (rawJson.value === null && !rawJson.loading && !rawJson.error) {
      void loadRaw()
    }
  }, [target, rawJson.value, rawJson.loading, rawJson.error, loadRaw])

  const extensions = useMemo(
    () => [json(), linter(jsonParseLinter()), editorTheme, EditorView.editable.of(false)],
    [],
  )

  if (rawJson.error) {
    return (
      <Reminder intent="caution" title={rawJson.error}>
        <button type="button" className="ql-raw-retry" onClick={() => loadRaw()}>retry</button>
      </Reminder>
    )
  }
  if (rawJson.loading || rawJson.value === null) {
    return <Reminder form="inline" intent="note">loading…</Reminder>
  }
  return (
    <div className="ql-raw-wrap">
      <div className="ql-raw-editor">
        <div className="ql-raw-actions">
          <button
            type="button"
            className="ql-raw-copy"
            onClick={() => navigator.clipboard?.writeText(rawJson.value ?? '')}
          >
            copy
          </button>
        </div>
        <CodeMirror
          value={rawJson.value}
          height="100%"
          theme="light"
          extensions={extensions}
          readOnly
          basicSetup={{ lineNumbers: true, foldGutter: false, highlightActiveLine: false }}
        />
      </div>
    </div>
  )
}

