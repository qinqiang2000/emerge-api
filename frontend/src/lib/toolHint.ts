export function toolShortHint(toolName: string, result: unknown): string | null {
  try {
    return unsafeToolShortHint(toolName, result)
  } catch {
    return null
  }
}

export function toolInputHint(toolName: string, input: unknown): string | null {
  try {
    return unsafeToolInputHint(toolName, input)
  } catch {
    return null
  }
}

function shorten(s: string, max = 60): string {
  return s.length <= max ? s : s.slice(0, max - 1) + '…'
}

function tailPath(p: string, segs = 2): string {
  const parts = p.split('/').filter(Boolean)
  if (parts.length <= segs) return p.startsWith('/') ? '/' + parts.join('/') : parts.join('/')
  return parts.slice(-segs).join('/')
}

function unsafeToolInputHint(toolName: string, input: unknown): string | null {
  if (!input || typeof input !== 'object') return null
  const o = input as Record<string, unknown>
  const bare = toolName.replace(/^mcp__emerge_tools__/, '')

  // SDK built-ins
  if (toolName === 'Read' || toolName === 'Write' || toolName === 'Edit' || toolName === 'NotebookEdit') {
    const p = typeof o.file_path === 'string' ? o.file_path
      : typeof o.notebook_path === 'string' ? o.notebook_path
      : null
    return p ? tailPath(p, 2) : null
  }
  if (toolName === 'Glob') {
    const pat = typeof o.pattern === 'string' ? o.pattern : null
    return pat ? shorten(pat) : null
  }
  if (toolName === 'Grep') {
    const pat = typeof o.pattern === 'string' ? o.pattern : ''
    const path = typeof o.path === 'string' ? tailPath(o.path, 2) : null
    return shorten(path ? `${pat} in ${path}` : pat) || null
  }
  if (toolName === 'Bash' || toolName === 'BashOutput') {
    const cmd = typeof o.command === 'string' ? o.command : null
    return cmd ? shorten(cmd, 70) : null
  }
  if (toolName === 'ToolSearch') {
    const q = typeof o.query === 'string' ? o.query : null
    return q ? shorten(q, 50) : null
  }
  if (toolName === 'WebFetch' || toolName === 'WebSearch') {
    const v = typeof o.url === 'string' ? o.url : typeof o.query === 'string' ? o.query : null
    return v ? shorten(v, 60) : null
  }

  // emerge MCP tools — show slug + the most action-defining param.
  const slug = typeof o.slug === 'string' ? o.slug : null
  switch (bare) {
    case 'write_schema': {
      const n = Array.isArray(o.schema) ? o.schema.length : null
      const hasNotes = typeof o.global_notes === 'string' && o.global_notes.length > 0
      const parts = [slug, n !== null ? `${n} fields` : null, hasNotes ? '+notes' : null].filter(Boolean)
      return parts.length ? parts.join(' · ') : null
    }
    case 'extract_one':
    case 'extract_batch':
    case 'pre_label':
    case 'save_reviewed': {
      const fn = typeof o.filename === 'string' ? o.filename : null
      const fns = Array.isArray(o.filenames) ? `${o.filenames.length} files` : null
      const target = fn ?? fns
      return [slug, target].filter(Boolean).join(' · ') || null
    }
    case 'read_doc_image':
    case 'ui_goto_page': {
      const fn = typeof o.filename === 'string' ? o.filename : null
      const page = typeof o.page === 'number' ? `p${o.page}` : null
      return [slug, fn, page].filter(Boolean).join(' · ') || null
    }
    case 'switch_active_prompt':
    case 'switch_active_model':
    case 'set_labeler_model': {
      const v = typeof o.prompt_id === 'string' ? o.prompt_id
        : typeof o.model_id === 'string' ? o.model_id
        : null
      return [slug, v].filter(Boolean).join(' → ') || null
    }
    default:
      return slug
  }
}

function unsafeToolShortHint(toolName: string, result: unknown): string | null {
  if (result === null || result === undefined) return null
  const bare = toolName.replace(/^mcp__emerge_tools__/, '')

  const asObj = (r: unknown): Record<string, unknown> | null => {
    if (typeof r === 'object' && r !== null) return r as Record<string, unknown>
    if (typeof r !== 'string') return null
    try {
      const parsed = JSON.parse(r)
      return typeof parsed === 'object' && parsed !== null ? parsed as Record<string, unknown> : null
    } catch {
      return null
    }
  }

  const countPyDicts = (s: string): number | null => {
    if (!/^\[.*\]$/s.test(s.trim())) return null
    const matches = s.match(/\{[^{}]*\}/g)
    return matches ? matches.length : 0
  }

  switch (bare) {
    case 'derive_schema':
    case 'read_schema': {
      if (typeof result !== 'string') return null
      const n = countPyDicts(result)
      if (n === null) return null
      return n === 1 ? '1 field' : `${n} fields`
    }
    case 'list_docs': {
      if (typeof result !== 'string') return null
      const n = countPyDicts(result)
      return n === null ? null : `${n} docs`
    }
    case 'list_reviewed': {
      if (typeof result !== 'string') return null
      const n = countPyDicts(result)
      return n === null ? null : `${n} reviewed`
    }
    case 'list_projects': {
      if (typeof result !== 'string') return null
      const n = countPyDicts(result)
      return n === null ? null : `${n} projects`
    }
    case 'extract_batch': {
      const o = asObj(result)
      const ok = typeof o?.ok_count === 'number' ? o.ok_count : null
      const err = typeof o?.err_count === 'number' ? o.err_count : null
      return ok === null || err === null ? null : `${ok}/${ok + err} ok`
    }
    case 'score': {
      const o = asObj(result)
      return typeof o?.macro_f1 === 'number' ? `macro_f1=${o.macro_f1.toFixed(2)}` : null
    }
    case 'freeze_version': {
      const o = asObj(result)
      return typeof o?.version_id === 'string' ? o.version_id : null
    }
    case 'issue_api_key': {
      const o = asObj(result)
      return typeof o?.key_prefix === 'string' ? o.key_prefix : null
    }
    case 'readiness_check': {
      const o = asObj(result)
      if (!Array.isArray(o?.checks)) return null
      const checks = o.checks as Array<{ status?: string }>
      const pass = checks.filter(c => c.status === 'pass').length
      return `${pass}/${checks.length} pass`
    }
    case 'contract_diff': {
      const o = asObj(result)
      if (!o) return null
      const added = Array.isArray(o.added) ? o.added.length : 0
      const removed = Array.isArray(o.removed) ? o.removed.length : 0
      const breaking = o.is_breaking === true ? ' (breaking)' : ''
      return `+${added} -${removed}${breaking}`
    }
    case 'start_job':
      return typeof result === 'string' && result.startsWith('j_') ? `job ${result.slice(0, 10)}` : null
    case 'get_job': {
      const o = asObj(result)
      return typeof o?.status === 'string' ? o.status : null
    }
    default:
      return null
  }
}
