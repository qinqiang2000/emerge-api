// Spike retirement guard (audit-board plan B3). The `?boardspike=1` dev page
// and its static assets are gone — the real board replaced them. This pins
// the retirement so a stale rebase can't resurrect the pre-auth dev branch,
// while the two pieces the board still depends on (the excalidraw dep + the
// vite IS_PREACT define) stay put.
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// vitest runs with cwd = frontend/ (where vite.config.ts lives)
const frontendRoot = process.cwd()
const repoRoot = resolve(frontendRoot, '..')

describe('spike retirement', () => {
  it('App.tsx carries no spike branch / import', () => {
    const src = readFileSync(`${frontendRoot}/src/App.tsx`, 'utf8')
    expect(src.toLowerCase()).not.toContain('spike')
    expect(src).not.toContain('boardspike')
  })

  it('src/spike/ and public/_boardspike/ are deleted', () => {
    expect(existsSync(`${frontendRoot}/src/spike`)).toBe(false)
    expect(existsSync(`${frontendRoot}/public/_boardspike`)).toBe(false)
  })

  it('.gitignore no longer carries the _boardspike entry', () => {
    const gitignore = readFileSync(`${repoRoot}/.gitignore`, 'utf8')
    expect(gitignore).not.toContain('_boardspike')
  })

  it('vite keeps the IS_PREACT define excalidraw needs at runtime', () => {
    const vite = readFileSync(`${frontendRoot}/vite.config.ts`, 'utf8')
    expect(vite).toContain("'process.env.IS_PREACT'")
  })

  it('the self-hosted excalidraw asset dir is in place (fonts)', () => {
    expect(existsSync(`${frontendRoot}/public/excalidraw-assets/fonts`)).toBe(true)
  })
})
