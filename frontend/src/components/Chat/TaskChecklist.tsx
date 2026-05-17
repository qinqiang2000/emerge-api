import { useMemo } from 'react'
import { CheckCircle2, Circle, CircleDot } from 'lucide-react'

import { useChat } from '../../stores/chat'
import type { ChatEvent, TaskEntry, TaskStatus } from '../../types/chat'

// ── deriveTasks ──────────────────────────────────────────────────────────
// Reads the chat event log and returns the *current* task list, derived from
// the most recent SDK task/todo tool call. Strategy:
//
//   - SDK's modern built-in is `TodoWrite` — input shape `{todos: [...]}` —
//     each call rewrites the whole list. Easy: take the last TodoWrite's
//     `tool_input.todos`.
//   - Older variant is the `TaskCreate` / `TaskUpdate` / `TaskList` triple
//     (incremental). If we see those instead of TodoWrite, fold them: walk
//     forwards, applying Create/Update by id and respecting TaskList resets.
//
// Either way, returning [] hides the panel. We deliberately do NOT track this
// in a separate store: deriving from `events` means chat-switch (events
// resets in the store) automatically wipes the panel without lifecycle
// plumbing — true SSU.
//
// Exported for unit testing.
export function deriveTasks(events: ChatEvent[]): TaskEntry[] {
  // Pass 1 — fast-path for TodoWrite (newest event wins).
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i]
    if (e.type !== 'tool_call') continue
    if (e.tool_name === 'TodoWrite' || e.tool_name === 'TodoUpdate') {
      const input = e.tool_input
      if (input && typeof input === 'object' && Array.isArray((input as Record<string, unknown>).todos)) {
        return parseTodoArray((input as Record<string, unknown>).todos as unknown[])
      }
    }
  }
  // Pass 2 — TaskCreate / TaskUpdate / TaskList fold (oldest-to-newest).
  const byId = new Map<string, TaskEntry>()
  let sawAnyTaskTool = false
  for (const e of events) {
    if (e.type !== 'tool_call') continue
    const n = e.tool_name
    if (n !== 'TaskCreate' && n !== 'TaskUpdate' && n !== 'TaskList' && n !== 'TaskStop') continue
    sawAnyTaskTool = true
    const input = (e.tool_input && typeof e.tool_input === 'object')
      ? e.tool_input as Record<string, unknown>
      : {}
    if (n === 'TaskList') {
      // Resets the whole list to whatever payload arrived (variants seen:
      // `{tasks: [...]}` or `{todos: [...]}`).
      const raw = (input.tasks ?? input.todos)
      if (Array.isArray(raw)) {
        byId.clear()
        for (const t of parseTodoArray(raw)) {
          byId.set(t.id ?? `t${byId.size}`, t)
        }
      }
      continue
    }
    if (n === 'TaskCreate') {
      const t = parseTodoEntry(input)
      if (t) {
        // SDK 0.2.x TaskCreate doesn't carry an ID in the input; the server
        // mints sequential string IDs ("1", "2", ...) that subsequent
        // TaskUpdate calls reference. Match by creation order so updates
        // land on the right entry.
        if (!t.id) {
          let nextId = 1
          while (byId.has(String(nextId))) nextId++
          t.id = String(nextId)
        }
        byId.set(t.id, t)
      }
      continue
    }
    if (n === 'TaskUpdate') {
      // SDK 0.2.82 uses `taskId`; older bundles used `id`. Accept either.
      const id = typeof input.taskId === 'string'
        ? input.taskId
        : (typeof input.id === 'string' ? input.id : null)
      if (!id) continue
      const prev = byId.get(id)
      if (!prev) {
        // Stand-alone update for an unknown id — surface as a new entry so
        // the panel doesn't silently drop it.
        const t = parseTodoEntry({ ...input })
        if (t) byId.set(id, t)
        continue
      }
      const next: TaskEntry = { ...prev }
      if (typeof input.content === 'string') next.content = input.content
      if (typeof input.subject === 'string') next.content = input.subject
      if (typeof input.activeForm === 'string') next.activeForm = input.activeForm
      const st = parseStatus(input.status)
      if (st) next.status = st
      byId.set(id, next)
      continue
    }
    if (n === 'TaskStop') {
      const id = typeof input.taskId === 'string'
        ? input.taskId
        : (typeof input.id === 'string' ? input.id : null)
      if (id && byId.has(id)) {
        const prev = byId.get(id)!
        byId.set(id, { ...prev, status: 'completed' })
      }
    }
  }
  return sawAnyTaskTool ? [...byId.values()] : []
}

function parseStatus(raw: unknown): TaskStatus | null {
  if (raw === 'pending' || raw === 'in_progress' || raw === 'completed') return raw
  return null
}

function parseTodoEntry(o: Record<string, unknown>): TaskEntry | null {
  // Field-name variants observed across SDK versions:
  //   - SDK 0.1.x TodoWrite / TaskCreate: `content` or `text`
  //   - SDK 0.2.x TaskCreate: `subject` (+ optional `description` for body)
  const content = typeof o.content === 'string'
    ? o.content
    : typeof o.text === 'string'
      ? o.text
      : (typeof o.subject === 'string' ? o.subject : null)
  if (!content) return null
  const t: TaskEntry = {
    content,
    status: parseStatus(o.status) ?? 'pending',
  }
  // SDK 0.2.x uses `taskId`; older variants used `id`.
  const id = typeof o.taskId === 'string'
    ? o.taskId
    : (typeof o.id === 'string' ? o.id : null)
  if (id) t.id = id
  if (typeof o.activeForm === 'string') t.activeForm = o.activeForm
  return t
}

function parseTodoArray(raw: unknown[]): TaskEntry[] {
  const out: TaskEntry[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const t = parseTodoEntry(item as Record<string, unknown>)
    if (t) out.push(t)
  }
  return out
}

// ── render ───────────────────────────────────────────────────────────────

function StatusIcon({ status }: { status: TaskStatus }) {
  if (status === 'completed') return <CheckCircle2 size={14} className="text-moss flex-shrink-0" />
  if (status === 'in_progress') return <CircleDot size={14} className="text-ochre flex-shrink-0" />
  return <Circle size={14} className="text-ink-4 flex-shrink-0" />
}

/** Live task checklist, rendered above the conv when the agent has an
 *  outstanding TodoWrite/Task list. Reads `events` directly so it auto-clears
 *  on chat switch (events resets). Style mirrors Claude Code's TodoWrite
 *  block: simple bullet list, status icon left, completed items strike-
 *  through + dimmed. */
export default function TaskChecklist() {
  // Select the raw events array (referential equality preserved by the chat
  // store across unrelated state updates), then derive tasks via useMemo —
  // calling `deriveTasks` inside the selector would build a fresh array on
  // every render and trip useSyncExternalStore's getSnapshot-must-be-cached
  // contract (infinite-loop crash).
  const events = useChat(s => s.events)
  const tasks = useMemo(() => deriveTasks(events), [events])
  if (tasks.length === 0) return null

  const completed = tasks.filter(t => t.status === 'completed').length

  return (
    <aside
      className="border border-rule-soft bg-paper-2 rounded-lg p-3 mb-4"
      role="region"
      aria-label="Agent task list"
      data-testid="task-checklist"
    >
      <div className="flex items-baseline gap-2 mb-2">
        <span className="font-mono text-[10.5px] uppercase tracking-wider text-ink-4">
          tasks
        </span>
        <span className="font-mono text-[10.5px] text-ink-4 tabular-nums">
          {completed}/{tasks.length}
        </span>
      </div>
      <ul className="flex flex-col gap-1">
        {tasks.map((t, i) => {
          const isDone = t.status === 'completed'
          const isLive = t.status === 'in_progress'
          const label = isLive && t.activeForm ? t.activeForm : t.content
          return (
            <li
              key={t.id ?? i}
              className={`flex items-start gap-2 font-sans text-[13px] leading-snug ${
                isDone ? 'text-ink-4 line-through' : 'text-ink'
              }`}
              data-testid="task-checklist-item"
              data-status={t.status}
            >
              <span className="pt-0.5"><StatusIcon status={t.status} /></span>
              <span className="min-w-0 break-words">{label}</span>
            </li>
          )
        })}
      </ul>
    </aside>
  )
}
