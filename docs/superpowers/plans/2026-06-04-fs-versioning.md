# 2026-06-04 — Filesystem versioning (per-team git history)

**Why now:** the 2026-06-04 data-loss incident (orphan cleanup rmtree'd `teams/`)
exposed that emerge's no-DB spine has durability (atomic writes) but no
*reversibility*. Tier 0 (soft-delete `_trash/`) shipped the safety net. This is
the history layer: full time-travel + agent-driven diff/restore.

**The reframe that dissolves "commit timing":** durability is already guaranteed
by `atomic_write_json` + flock. Git only adds *versioning*. So a missed/late
commit loses a history point, never data — commits can be best-effort/eventual.

## Shape

- **One git repo per effective workspace.** Tenant mode: `teams/{slug}/.git`.
  Open mode: the flat root. Per-team = matches the isolation boundary (an agent
  with shell access sees only its own team's history) and keeps `_auth/` +
  `_keys.json` (true root) OUT of any repo (no secrets committed).
- **`git` CLI via subprocess** (no new dep; stdlib-first). Sync wrapper;
  async callers use `asyncio.to_thread`. Per-repo `threading.Lock` serializes
  our commits (git's own `index.lock` covers cross-process).
- **`.gitignore`** the derivable/transient: `.cache/ _staging/ _trash/
  _job_locks/ _chats/ chats/`. Versions the artifact state: project.json,
  prompts/models/schema, global_notes, docs (source), predictions, experiments,
  versions/, _published, reviewed.

## Commit cadence (semantic + catch-all)

| trigger | granularity | message |
|---|---|---|
| agent turn end (`chat/service.py`) | one user intent | turn label/summary |
| job end (`JobRunner`) | one extract/tune | job kind + project |
| periodic checkpoint (bg task) | catch-all for route/headless writes | `checkpoint` |
| startup | `ensure_repo` + initial snapshot | `init` / `checkpoint` |

## Agent-facing (同事精神 + 三形对称) — the point of the tip

History is reachable from chat, not just background. Each `@tool` + HTTP route +
MCP, with `browser`/`headless` rendering contracts:

- `history_log` — version timeline (workspace- or project-scoped)
- `history_diff <a> <b>` — what changed between two versions (schema/prompt/notes)
- `history_restore <ref>` — restore a historical version; the restore is ITSELF
  a new commit (forward-moving, reversible)

## Phasing

1. **Foundation** — `workspace/history.py` (ensure_repo, commit_all, log, diff,
   restore) + unit tests + startup `ensure_repo`. *(this increment)*
2. **Triggers** — turn-end + job-end commits + periodic checkpoint bg task.
3. **Agent tools** — log/diff/restore as tool+route+MCP with render contracts.

## Risks / decisions

- **Binary bloat** (docs PDFs): write-once, bounded; gitignore covers all
  derivable caches. Revisit LFS only if it bites. Don't preempt.
- **Concurrency**: commits are best-effort snapshots; atomic writes mean any
  file caught mid-flight is still whole. A partial binary in one commit is
  corrected in the next — not a correctness issue (durability ≠ versioning).
- **git absent**: degrade gracefully (log once, no-op) — never break the app.
