export function toolShortHint(toolName: string, result: unknown): string | null {
  try {
    return unsafeToolShortHint(toolName, result)
  } catch {
    return null
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
