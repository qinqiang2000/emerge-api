// Co-located Composer drop/paste test. The composer accepts drops in two
// shapes: a plain `dataTransfer.files` (legacy, single-level) or the entries
// API (`dataTransfer.items[i].webkitGetAsEntry()`) which is the only path
// that exposes folder structure. We exercise the entries path here because
// folder + non-doc drops are the whole point of `2026-05-26-folder-and-schema-drop`.

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import Composer from './Composer'

describe('Composer draft persistence', () => {
  it('same draftKey → text survives unmount/remount (chat → review → back)', () => {
    const { unmount } = render(
      <Composer disabled={false} pending={[]} onAttach={vi.fn()} onSubmit={vi.fn()} draftKey="main:p_a:c1" />,
    )
    const ta = () => screen.getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(ta(), { target: { value: '123' } })
    // Opening a review doc unmounts ChatPanel + this composer.
    unmount()
    // Esc back → composer remounts with the same key.
    render(
      <Composer disabled={false} pending={[]} onAttach={vi.fn()} onSubmit={vi.fn()} draftKey="main:p_a:c1" />,
    )
    expect(ta().value).toBe('123')
  })

  it('different draftKey → independent drafts (per conversation)', () => {
    const { unmount } = render(
      <Composer disabled={false} pending={[]} onAttach={vi.fn()} onSubmit={vi.fn()} draftKey="main:p_a:c1" />,
    )
    const ta = () => screen.getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(ta(), { target: { value: 'hello c1' } })
    unmount()
    // A different conversation's composer must not inherit c1's draft.
    render(
      <Composer disabled={false} pending={[]} onAttach={vi.fn()} onSubmit={vi.fn()} draftKey="main:p_a:c2" />,
    )
    expect(ta().value).toBe('')
  })

  it('submit clears the persisted draft', () => {
    const onSubmit = vi.fn()
    const { unmount } = render(
      <Composer disabled={false} pending={[]} onAttach={vi.fn()} onSubmit={onSubmit} draftKey="main:p_a:c3" />,
    )
    const ta = () => screen.getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(ta(), { target: { value: 'sent message' } })
    fireEvent.keyDown(ta(), { key: 'Enter' })
    expect(onSubmit).toHaveBeenCalledWith('sent message')
    unmount()
    render(
      <Composer disabled={false} pending={[]} onAttach={vi.fn()} onSubmit={vi.fn()} draftKey="main:p_a:c3" />,
    )
    expect(ta().value).toBe('')
  })

  it('no draftKey → ephemeral, nothing persists across remount', () => {
    const { unmount } = render(
      <Composer disabled={false} pending={[]} onAttach={vi.fn()} onSubmit={vi.fn()} />,
    )
    const ta = () => screen.getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(ta(), { target: { value: 'transient' } })
    unmount()
    render(<Composer disabled={false} pending={[]} onAttach={vi.fn()} onSubmit={vi.fn()} />)
    expect(ta().value).toBe('')
  })
})

// --- Tiny FileSystemEntry mock harness -------------------------------------
//
// The entries API is `webkitGetAsEntry()` returning either a `FileSystemFileEntry`
// (`isFile=true`, `file(cb, errCb)`) or a `FileSystemDirectoryEntry`
// (`isDirectory=true`, `createReader().readEntries(cb, errCb)` — note: the
// reader hands out batches and returns [] when exhausted, so the recursive
// walker must keep calling until empty). The composer also reads `entry.name`
// for path stitching. We model both shapes minimally.
// Explicit mock entry types — `dirEntry` is recursive (a dir holds dirs), so
// an explicit return annotation is required to break the self-referential
// `ReturnType<typeof dirEntry>` inference cycle.
type FileEntryMock = ReturnType<typeof fileEntry>
type DirEntryMock = {
  isFile: false
  isDirectory: true
  name: string
  createReader: () => { readEntries: (cb: (entries: FsEntryMock[]) => void) => void }
}
type FsEntryMock = FileEntryMock | DirEntryMock

function fileEntry(name: string, content = '') {
  const file = new File([content], name, { type: 'text/plain' })
  return {
    isFile: true,
    isDirectory: false,
    name,
    file: (cb: (f: File) => void) => cb(file),
  }
}

function dirEntry(name: string, children: FsEntryMock[]): DirEntryMock {
  // readEntries hands out children in one batch then [] — matches the
  // browser's contract closely enough for the walker (which keeps calling
  // until an empty batch). Multi-batch behavior is exercised via a separate
  // dirEntryBatched helper if needed.
  let drained = false
  return {
    isFile: false,
    isDirectory: true,
    name,
    createReader: () => ({
      readEntries: (cb: (entries: typeof children) => void) => {
        if (drained) return cb([])
        drained = true
        cb(children)
      },
    }),
  }
}

function makeDataTransfer(items: Array<FsEntryMock | null>) {
  // Mirror enough of DataTransfer for the drop handler — `files` is empty
  // (the entries API is what carries the structure) and `items[i]` exposes
  // `webkitGetAsEntry()` returning the canned entry. `kind: 'file'` matches
  // what the browser would emit for a real drop.
  return {
    files: [] as unknown as FileList,
    items: items.map(entry => ({
      kind: 'file' as const,
      type: '',
      webkitGetAsEntry: () => entry,
      // getAsFile is the entries-API fallback the paste handler uses when
      // webkitGetAsEntry returns null. Tests that exercise the fallback set
      // `entry: null` and provide `getAsFile` via a separate factory.
      getAsFile: () => null,
    })),
  }
}

describe('Composer drop/paste — entries API', () => {
  it('single file drop → onAttach called with one File', async () => {
    const onAttach = vi.fn()
    const onAttachFailed = vi.fn()
    render(
      <Composer
        disabled={false}
        pending={[]}
        onAttach={onAttach}
        onAttachFailed={onAttachFailed}
        onSubmit={vi.fn()}
      />,
    )
    const wrap = document.querySelector('.composer-wrap')!
    fireEvent.drop(wrap, { dataTransfer: makeDataTransfer([fileEntry('hello.pdf')]) })
    await waitFor(() => expect(onAttach).toHaveBeenCalledTimes(1))
    const files = onAttach.mock.calls[0][0] as File[]
    expect(files).toHaveLength(1)
    expect(files[0].name).toBe('hello.pdf')
    expect(onAttachFailed).not.toHaveBeenCalled()
  })

  it('folder drop → recurses into nested files; __relPath populated', async () => {
    const onAttach = vi.fn()
    render(
      <Composer disabled={false} pending={[]} onAttach={onAttach} onSubmit={vi.fn()} />,
    )
    // batch/   nested/  a.pdf
    //          b.pdf
    //          c.pdf
    const folder = dirEntry('batch', [
      dirEntry('nested', [fileEntry('a.pdf'), fileEntry('b.pdf')]),
      fileEntry('c.pdf'),
    ])
    const wrap = document.querySelector('.composer-wrap')!
    fireEvent.drop(wrap, { dataTransfer: makeDataTransfer([folder]) })
    await waitFor(() => expect(onAttach).toHaveBeenCalledTimes(1))
    const files = onAttach.mock.calls[0][0] as File[]
    expect(files).toHaveLength(3)
    const byName = Object.fromEntries(files.map(f => [f.name, f]))
    // The walker rewrites __relPath only when it differs from the bare name.
    // Top-level files inside the dropped folder still pick up the folder
    // prefix; nested ones get the full chain.
    const rel = (f: File) => (f as unknown as { __relPath?: string }).__relPath
    expect(rel(byName['a.pdf'])).toBe('batch/nested/a.pdf')
    expect(rel(byName['b.pdf'])).toBe('batch/nested/b.pdf')
    expect(rel(byName['c.pdf'])).toBe('batch/c.pdf')
  })

  it('empty folder drop → onAttachFailed with composer.dropEmpty', async () => {
    const onAttach = vi.fn()
    const onAttachFailed = vi.fn()
    render(
      <Composer
        disabled={false}
        pending={[]}
        onAttach={onAttach}
        onAttachFailed={onAttachFailed}
        onSubmit={vi.fn()}
      />,
    )
    const empty = dirEntry('hollow', [])
    const wrap = document.querySelector('.composer-wrap')!
    fireEvent.drop(wrap, { dataTransfer: makeDataTransfer([empty]) })
    await waitFor(() => expect(onAttachFailed).toHaveBeenCalledTimes(1))
    expect(onAttachFailed.mock.calls[0][0]).toBe('composer.dropEmpty')
    expect(onAttach).not.toHaveBeenCalled()
  })

  it('paste with a directory entry → recurses like drop', async () => {
    const onAttach = vi.fn()
    render(
      <Composer disabled={false} pending={[]} onAttach={onAttach} onSubmit={vi.fn()} />,
    )
    const folder = dirEntry('docs', [fileEntry('one.pdf'), fileEntry('two.pdf')])
    const ta = screen.getByRole('textbox') as HTMLTextAreaElement
    // Build a clipboard payload that exposes items but no `files` — the paste
    // handler must walk items via webkitGetAsEntry. `kind: 'file'` triggers
    // the file-shaped branch (text-only pastes early-return without preventing
    // the textarea's default).
    fireEvent.paste(ta, {
      clipboardData: {
        files: [] as unknown as FileList,
        items: [
          {
            kind: 'file',
            type: '',
            webkitGetAsEntry: () => folder,
            getAsFile: () => null,
          },
        ],
      },
    })
    await waitFor(() => expect(onAttach).toHaveBeenCalledTimes(1))
    const files = onAttach.mock.calls[0][0] as File[]
    expect(files.map(f => f.name).sort()).toEqual(['one.pdf', 'two.pdf'])
  })
})
