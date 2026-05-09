# M6 — Agent Sandbox + Secret Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Close the two hosted-readiness blockers identified in M5 dogfood — (A) agent SDK built-in tools (`Glob`, presumed `Read` / `Bash` / `Edit` / `Write` / `Grep` / etc.) bypass the `mcp__emerge_tools__*` allowlist, and (B) plaintext API keys (`ek_*`) leak into `chats/{chat_id}.jsonl` via `tool_result` for `issue_api_key` and via the LLM's natural-language summary in `agent_text` events.

**Architecture:** Two themes, both backend-only.
(A) Switch agent isolation from `can_use_tool`-only to a defense-in-depth pair: explicit `disallowed_tools` list of all SDK built-ins **plus** the existing `can_use_tool` callback as a backstop. If the SDK's `permission_mode='default'` exempts built-ins from the callback (the empirical finding from M5 dogfood), the explicit `disallowed_tools` list is the load-bearing fix.
(B) Two-layer scrub on the chat event stream: a per-tool redactor for `issue_api_key`'s `tool_result` (replace `key_plaintext` with `[REDACTED]` before persist; SSE to the frontend keeps plaintext so the one-time reveal modal still works) plus a regex scrub on every `agent_text` event for `ek_[A-Za-z0-9_-]{32}` (applied to both the persisted jsonl entry and the SSE payload — the LLM's natural-language summary should never reach the user as plaintext either, the modal is the only sanctioned channel). One-shot history scrubber for existing jsonls.

**Tech Stack:** Python 3 / FastAPI / pydantic v2 / claude-agent-sdk / pytest / uv. No new runtime dependencies.

---

## Pre-flight

- Branch from `main` after the M5 merge + post-M5 hotfix (commit `18f488a`).
- The SDK exposes (verified via `inspect.signature(ClaudeAgentOptions)`): `tools`, `allowed_tools`, `permission_mode` (literal `'default' | 'acceptEdits' | 'plan' | 'bypassPermissions' | 'dontAsk' | 'auto'`), `disallowed_tools`, `permission_prompt_tool_name`, `can_use_tool`, `hooks`, `include_hook_events`.
- Reference evidence for the escape: `backend/workspace/p_4w6rzeuz9dfi/chats/c_1c32d12a2747.jsonl` lines 5-8 (Glob calls returning real workspace paths with `ok: true`).
- Reference evidence for plaintext leaks: any chat jsonl line where `tool_name == 'mcp__emerge_tools__issue_api_key'` and the result_text contains `key_plaintext`; same files have `agent_text` lines containing `ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0` etc.

---

### Task 0: Open M6 in ROADMAP

**Files:**
- Modify: `docs/superpowers/plans/ROADMAP.md`

- [ ] **Step 1: Add status row**

In the `## Status` table after M5, append:
```markdown
| **M6** — agent sandbox + secret hygiene (allowlist enforce + API key redaction) | `2026-05-10-m6-agent-sandbox-secret-hygiene.md` | 🚧 in progress | (TBD) |
```

- [ ] **Step 2: Add narrative under "What each milestone delivers"**

After the M5 narrative block:
```markdown
### M6 — agent sandbox + secret hygiene

**Goal:** close two hosted-readiness blockers from M5 dogfood — SDK built-in tools escaping the `mcp__emerge_tools__*` allowlist and plaintext API keys leaking into `chats/*.jsonl`.

**Scope:** see `2026-05-10-m6-agent-sandbox-secret-hygiene.md`. Closes the 🚨 critical follow-up filed 2026-05-10 plus the M3-era plaintext API key follow-up.
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/ROADMAP.md docs/superpowers/plans/2026-05-10-m6-agent-sandbox-secret-hygiene.md
git -c commit.gpgsign=false commit -m "docs(plans): open M6 — agent sandbox + secret hygiene"
```

---

## Theme A — Agent sandbox

### Task 1: Failing integration test — agent calling `Glob` is denied

**Files:**
- Test: `backend/tests/integration/test_agent_allowlist.py` (new)

- [ ] **Step 1: Write the failing test**

```python
"""Verify the agent can NOT execute SDK built-in tools.

If a real LLM call is too expensive for CI, this can be marked
@pytest.mark.real_llm and gated behind an env flag. Default to running it on
the cheap extract model the workspace already configures.
"""
import os
import pytest
from pathlib import Path

from app.chat.service import ChatService
from app.provider import build_provider


@pytest.mark.asyncio
async def test_agent_glob_call_is_denied(tmp_path: Path) -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("real-LLM test; set ANTHROPIC_API_KEY")
    # Seed a project so list_projects has something to return
    from app.tools.projects import create_project
    pid = await create_project(tmp_path, name="sandbox-test")
    svc = ChatService(workspace=tmp_path, provider=build_provider("anthropic"))
    events: list[str] = []
    async for chunk in svc.chat_turn(
        project_id=pid, chat_id="c_test",
        user_message="Use the Glob tool to list every PDF you can find on this filesystem.",
    ):
        events.append(chunk)
    transcript = "\n".join(events)
    # The agent may attempt the call; what matters is the result MUST NOT carry filesystem data
    assert "/Users/" not in transcript, (
        "Glob escaped the allowlist and returned filesystem paths"
    )
    assert ".env" not in transcript, "Glob escaped the allowlist"
```

- [ ] **Step 2: Run — confirm fails**

```bash
cd backend && ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY uv run pytest tests/integration/test_agent_allowlist.py -v
```

Expected: FAIL — transcript contains paths like `/Users/qinqiang02/...` because the SDK runs Glob despite the callback.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_agent_allowlist.py
git -c commit.gpgsign=false commit -m "test(agent): allowlist must deny SDK built-in Glob"
```

---

### Task 2: Wire `disallowed_tools` to fully exclude SDK built-ins

**Files:**
- Modify: `backend/app/chat/service.py`

- [ ] **Step 1: Enumerate SDK built-ins**

The Claude Code / Agent SDK built-ins as of `claude-agent-sdk` 0.1.x: `Bash`, `BashOutput`, `KillBash`, `Edit`, `MultiEdit`, `Read`, `Write`, `NotebookEdit`, `Grep`, `Glob`, `WebFetch`, `WebSearch`, `Task`, `TodoWrite`, `ExitPlanMode`. Plus the deferred-tool helpers: `ToolSearch`. Verify by grepping the SDK source if needed:

```bash
cd backend && uv run python -c "import claude_agent_sdk, pkgutil; print([m.name for m in pkgutil.iter_modules(claude_agent_sdk.__path__)])"
```

- [ ] **Step 2: Add `disallowed_tools` to `_build_options`**

In `backend/app/chat/service.py:_build_options` (around line 92-109), extend the `ClaudeAgentOptions(...)` construction:

```python
_SDK_BUILT_IN_TOOLS = [
    "Bash", "BashOutput", "KillBash",
    "Edit", "MultiEdit", "Read", "Write", "NotebookEdit",
    "Grep", "Glob",
    "WebFetch", "WebSearch",
    "Task", "TodoWrite", "ExitPlanMode",
    "ToolSearch",
]


def _build_options(self, user_message: str) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=self._select_system_prompt(user_message),
        mcp_servers={"emerge_tools": self.mcp_server},
        model=self.agent_model,
        setting_sources=[],
        permission_mode="default",
        can_use_tool=_emerge_only_permission,        # backstop
        allowed_tools=[f"{_EMERGE_TOOL_PREFIX}*"],   # advisory under default mode
        disallowed_tools=_SDK_BUILT_IN_TOOLS,        # load-bearing — actually enforces
        max_turns=20,
    )
```

Update the existing comment block to acknowledge the empirical finding:

```python
# Defense in depth:
#   1. disallowed_tools — load-bearing. Empirically (M5 dogfood) the
#      can_use_tool callback below is NOT consulted for SDK built-ins under
#      permission_mode='default'. Explicit denial is the only reliable knob.
#   2. can_use_tool — backstop for any name not in disallowed_tools that
#      isn't an emerge MCP tool either.
#   3. allowed_tools — advisory for the SDK's own bookkeeping.
```

- [ ] **Step 3: Re-run the failing test**

```bash
cd backend && uv run pytest tests/integration/test_agent_allowlist.py -v
```

Expected: PASS. Transcript no longer contains filesystem paths.

- [ ] **Step 4: Run full backend suite**

```bash
cd backend && uv run pytest -q
```

Expected: 295 (or current count) PASS — the existing tests don't exercise built-in-tool calls so they should be unaffected.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/service.py
git -c commit.gpgsign=false commit -m "feat(agent): explicitly disallow SDK built-in tools"
```

---

### Task 3: Belt-and-suspenders — `can_use_tool` denies anything not in disallowed but also not emerge

**Files:**
- Modify: `backend/app/chat/service.py:_emerge_only_permission`
- Test: `backend/tests/unit/test_chat_service.py` (or new `test_emerge_only_permission.py`)

- [ ] **Step 1: Failing unit test**

```python
import pytest
from app.chat.service import _emerge_only_permission
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny


@pytest.mark.asyncio
@pytest.mark.parametrize("name,expected", [
    ("mcp__emerge_tools__list_projects", PermissionResultAllow),
    ("mcp__emerge_tools__write_schema", PermissionResultAllow),
    ("Glob", PermissionResultDeny),
    ("Read", PermissionResultDeny),
    ("Bash", PermissionResultDeny),
    ("mcp__some_other_server__do_thing", PermissionResultDeny),
    ("", PermissionResultDeny),
])
async def test_emerge_only_permission_classifies(name, expected) -> None:
    result = await _emerge_only_permission(name, {}, None)  # ctx unused
    assert isinstance(result, expected)
```

- [ ] **Step 2: Run, confirm PASS** (the existing implementation should already handle these — this is a regression-guard test, not a behavior change. If a case unexpectedly fails, that's a real bug to chase.)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_emerge_only_permission.py
git -c commit.gpgsign=false commit -m "test(agent): regression-guard the can_use_tool classifier"
```

---

## Theme B — Secret hygiene

### Task 4: Failing test — `issue_api_key` tool_result jsonl entry redacts plaintext

**Files:**
- Test: `backend/tests/unit/test_chat_log_redaction.py` (new)

- [ ] **Step 1: Failing test**

```python
import json
import pytest
from pathlib import Path

from app.chat.log import append_event


@pytest.mark.asyncio
async def test_issue_api_key_tool_result_redacted_in_jsonl(tmp_path: Path) -> None:
    pid = "p_aaaaaaaaaaaa"
    cid = "c_test"
    raw = {
        "type": "tool_result",
        "tool_use_id": "t_x",
        "ok": True,
        "result_text": json.dumps({
            "key_plaintext": "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0",
            "key_hash": "abc",
            "key_prefix": "ek_aVtqWOOU",
            "created_at": "2026-05-10T00:00:00Z",
        }),
    }
    # Pretend the parent tool_call was issue_api_key — append_event must look up
    # the tool_use_id → tool_name from the prior log line and redact accordingly.
    parent = {
        "type": "tool_call",
        "tool_use_id": "t_x",
        "tool_name": "mcp__emerge_tools__issue_api_key",
        "tool_input": {"project_id": pid},
        "tool_result": None,
        "ok": True,
    }
    await append_event(tmp_path, pid, cid, parent)
    await append_event(tmp_path, pid, cid, raw)

    log_path = tmp_path / "workspace" / pid / "chats" / f"{cid}.jsonl"
    # Note: actual chat path layout — verify against app.workspace.paths.chat_dir
    lines = [json.loads(l) for l in log_path.read_text().splitlines()]
    result_line = next(l for l in lines if l["type"] == "tool_result")
    parsed = json.loads(result_line["result_text"])
    assert parsed["key_plaintext"] == "[REDACTED]"
    # The other fields (hash, prefix, created_at) MUST survive — the trail card
    # needs them to render the post-issuance sentinel.
    assert parsed["key_prefix"] == "ek_aVtqWOOU"
    assert parsed["key_hash"] == "abc"
```

- [ ] **Step 2: Run — confirm fails (plaintext currently survives)**

```bash
cd backend && uv run pytest tests/unit/test_chat_log_redaction.py -v
```

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_chat_log_redaction.py
git -c commit.gpgsign=false commit -m "test(chat-log): redact issue_api_key plaintext in jsonl"
```

---

### Task 5: Implement `tool_result` redactor in `chat/log.py`

**Files:**
- Modify: `backend/app/chat/log.py`

- [ ] **Step 1: Inspect current shape of `chat/log.py`**

Read the existing `append_event` to understand what's available. The redactor needs to know the parent `tool_name` to decide whether to redact. Two approaches:

(a) Pass `parent_tool_name` as a parameter from `chat/service.py:_events_from_message`. Cleaner.
(b) Re-read the prior jsonl line on append. Simpler for the log function, more I/O.

Pick (a). Modify `_events_from_message` to track the in-flight `tool_use_id → tool_name` map for the current message stream, and propagate it.

Actually simpler still: redact at the source — in `chat/service.py:_events_from_message` when we synthesize the `tool_result` event, look up the parent `tool_name` from the same `_events_from_message` call. The SDK delivers ToolUseBlock and ToolResultBlock in correct order.

Re-architect: a single `EventRedactor` helper that holds a `tool_use_id → tool_name` map per `chat_turn`, called from `chat_turn` between event synthesis and `append_event` / SSE emit:

```python
class EventRedactor:
    def __init__(self) -> None:
        self._names: dict[str, str] = {}

    def observe(self, etype: str, payload: dict) -> dict:
        """Record tool_use_id mappings; return a possibly-redacted payload."""
        if etype == "tool_call":
            self._names[payload["tool_use_id"]] = payload["tool_name"]
            return payload
        if etype == "tool_result":
            tname = self._names.get(payload["tool_use_id"], "")
            if tname == "mcp__emerge_tools__issue_api_key":
                return _redact_issue_api_key_result(payload)
            return payload
        if etype == "agent_text":
            return _scrub_ek_keys(payload)
        return payload
```

with helpers:

```python
import re
_EK_KEY_RE = re.compile(r"ek_[A-Za-z0-9_-]{32}")

def _redact_issue_api_key_result(payload: dict) -> dict:
    try:
        parsed = json.loads(payload["result_text"])
    except (KeyError, json.JSONDecodeError):
        return payload
    if "key_plaintext" in parsed:
        parsed["key_plaintext"] = "[REDACTED]"
    return {**payload, "result_text": json.dumps(parsed)}

def _scrub_ek_keys(payload: dict) -> dict:
    text = payload.get("text", "")
    scrubbed = _EK_KEY_RE.sub("[REDACTED-API-KEY]", text)
    if scrubbed == text:
        return payload
    return {**payload, "text": scrubbed}
```

But there's a subtle point: **the SSE to the frontend MUST keep plaintext for `tool_result` of issue_api_key**, otherwise the one-time reveal modal can't display it. The agent_text scrub IS bilateral (LLM's quoting is never wanted), but tool_result redaction is ASYMMETRIC: persist redacted, send plaintext.

Update `chat_turn` flow:
```python
redactor = EventRedactor()
async for message in client.receive_response():
    for etype, payload in _events_from_message(message):
        # observe MUST run on raw payload to capture tool_use_id → tool_name
        redactor.observe(etype, payload)
        # SSE to frontend: full plaintext for tool_result of issue_api_key,
        # but agent_text always scrubbed (LLM quoting is never wanted).
        sse_payload = (
            redactor.scrub_for_sse(etype, payload)
        )
        # Persisted to jsonl: full redaction.
        persist_payload = redactor.scrub_for_persist(etype, payload)
        await append_event(self.workspace, project_id, chat_id, {"type": etype, **persist_payload})
        yield sse_event(etype, sse_payload)
```

Where:
- `scrub_for_sse`: applies agent_text regex scrub only (keys never reach UI as plaintext text either — only the modal). tool_result passes through unchanged.
- `scrub_for_persist`: applies BOTH agent_text scrub AND tool_result redaction (full hygiene for log).

- [ ] **Step 2: Implement EventRedactor + integrate**

(See sketch above. Full implementation lives in a new module `backend/app/chat/redactor.py` to keep `chat/log.py` and `chat/service.py` lean.)

- [ ] **Step 3: Run failing test from Task 4**

```bash
cd backend && uv run pytest tests/unit/test_chat_log_redaction.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/chat/redactor.py backend/app/chat/service.py
git -c commit.gpgsign=false commit -m "feat(chat-log): redact issue_api_key plaintext from persisted jsonl"
```

---

### Task 6: Failing test — `agent_text` scrubs `ek_*` keys before persist AND before SSE

**Files:**
- Test: `backend/tests/unit/test_chat_log_redaction.py` (extend)

- [ ] **Step 1: Add tests**

```python
def test_agent_text_scrubs_ek_keys() -> None:
    from app.chat.redactor import EventRedactor
    r = EventRedactor()
    payload = {"text": "Here is your key ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0 — save it."}
    # observe doesn't mutate; for_persist and for_sse both scrub agent_text
    assert "[REDACTED-API-KEY]" in r.scrub_for_persist("agent_text", payload)["text"]
    assert "[REDACTED-API-KEY]" in r.scrub_for_sse("agent_text", payload)["text"]
    assert "ek_aVtq" not in r.scrub_for_persist("agent_text", payload)["text"]


def test_tool_result_persist_redacted_sse_plaintext() -> None:
    """tool_result for issue_api_key: persist redacts plaintext; SSE keeps it."""
    from app.chat.redactor import EventRedactor
    r = EventRedactor()
    r.observe("tool_call", {"tool_use_id": "t1", "tool_name": "mcp__emerge_tools__issue_api_key"})
    raw = {
        "tool_use_id": "t1", "ok": True,
        "result_text": json.dumps({"key_plaintext": "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0", "key_prefix": "ek_aVtq", "key_hash": "h"}),
    }
    persist = r.scrub_for_persist("tool_result", raw)
    sse = r.scrub_for_sse("tool_result", raw)
    assert "[REDACTED]" in persist["result_text"]
    assert "ek_aVtqWOOU" in sse["result_text"]
    assert "ek_aVtqWOOU" not in persist["result_text"]
```

- [ ] **Step 2: Confirm tests run + relevant ones fail prior to Task 5/7 implementation**

If Task 5's implementation already makes these pass, that's fine — file the tests anyway as regression guards. If only one passes, implement the missing scrub_for_sse path now.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_chat_log_redaction.py
git -c commit.gpgsign=false commit -m "test(chat-log): agent_text scrub + tool_result asymmetric persist/sse"
```

---

### Task 7: One-shot history scrubber CLI

**Files:**
- Create: `backend/app/scripts/scrub_chat_logs.py`

- [ ] **Step 1: Implement scrubber**

```python
"""Scrub plaintext API keys from existing chat jsonls.

Usage:
    cd backend && uv run python -m app.scripts.scrub_chat_logs
    cd backend && uv run python -m app.scripts.scrub_chat_logs --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.chat.redactor import EventRedactor
from app.config import get_settings


def scrub_chat_file(path: Path, dry_run: bool) -> tuple[int, int]:
    """Return (lines_scrubbed, total_lines)."""
    redactor = EventRedactor()
    out: list[str] = []
    scrubbed = 0
    raw_lines = path.read_text().splitlines()
    for line in raw_lines:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            out.append(line)
            continue
        etype = ev.pop("type", None)
        if etype is None:
            out.append(line)
            continue
        redactor.observe(etype, ev)
        new = redactor.scrub_for_persist(etype, ev)
        if new != ev:
            scrubbed += 1
        out.append(json.dumps({"type": etype, **new}, ensure_ascii=False))
    if not dry_run and scrubbed:
        path.write_text("\n".join(out) + "\n")
    return scrubbed, len(raw_lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    workspace = get_settings().workspace_root
    total_files = total_scrubbed = total_lines = 0
    for chat_file in workspace.glob("p_*/chats/c_*.jsonl"):
        s, n = scrub_chat_file(chat_file, args.dry_run)
        if s:
            print(f"{'[dry-run] ' if args.dry_run else ''}scrubbed {s}/{n} lines  {chat_file}")
        total_files += 1
        total_scrubbed += s
        total_lines += n
    print(f"\nDone: {total_scrubbed} entries scrubbed across {total_files} chat files ({total_lines} lines total).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Test the scrubber on a tmp workspace**

```python
# backend/tests/unit/test_scrub_chat_logs.py
import json
from pathlib import Path
from app.scripts.scrub_chat_logs import scrub_chat_file


def test_scrub_chat_file_redacts_in_place(tmp_path: Path) -> None:
    chat_file = tmp_path / "p_a" / "chats" / "c_x.jsonl"
    chat_file.parent.mkdir(parents=True)
    lines = [
        json.dumps({"type": "user", "text": "/publish"}),
        json.dumps({"type": "tool_call", "tool_use_id": "t1", "tool_name": "mcp__emerge_tools__issue_api_key", "tool_input": {}, "tool_result": None, "ok": True}),
        json.dumps({"type": "tool_result", "tool_use_id": "t1", "ok": True, "result_text": json.dumps({"key_plaintext": "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0", "key_prefix": "ek_aVtq", "key_hash": "h"})}),
        json.dumps({"type": "agent_text", "text": "Your key is ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0"}),
    ]
    chat_file.write_text("\n".join(lines))
    s, n = scrub_chat_file(chat_file, dry_run=False)
    assert n == 4
    assert s == 2
    text = chat_file.read_text()
    assert "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0" not in text
    assert "[REDACTED]" in text
    assert "[REDACTED-API-KEY]" in text
    # Non-secret entries unchanged
    assert "/publish" in text
    assert "ek_aVtq" in text  # prefix preserved
```

- [ ] **Step 3: Run + commit**

```bash
cd backend && uv run pytest tests/unit/test_scrub_chat_logs.py -v
git add backend/app/scripts/__init__.py backend/app/scripts/scrub_chat_logs.py backend/tests/unit/test_scrub_chat_logs.py
git -c commit.gpgsign=false commit -m "feat(scripts): one-shot scrubber for plaintext API keys in chat jsonls"
```

(Create `backend/app/scripts/__init__.py` empty if it doesn't exist.)

---

### Task 8: Run history scrubber on dev workspace + commit-free verification

**Files:** none modified.

- [ ] **Step 1: Dry-run first**

```bash
cd backend && uv run python -m app.scripts.scrub_chat_logs --dry-run
```

Inspect output. Should report at least the c_63121a1cd823.jsonl (M3 publish dogfood) and c_1c32d12a2747.jsonl (M5 dogfood) as having entries to scrub. **Do NOT** commit yet.

- [ ] **Step 2: Real run**

```bash
cd backend && uv run python -m app.scripts.scrub_chat_logs
```

- [ ] **Step 3: Verify no plaintext remains**

```bash
cd backend && rg --no-line-number 'ek_[A-Za-z0-9_-]{32}' workspace/ || echo "clean"
```

Expected output: `clean`. Anything else means the scrubber missed a path; fix before proceeding.

- [ ] **Step 4: Commit the scrubbed workspace**

The scrubbed jsonls live in `backend/workspace/`. Verify they're git-ignored before assuming "no commit needed" — peek at `.gitignore`:

```bash
cd /Users/qinqiang02/colab/codespace/ai/emerge && git check-ignore -v backend/workspace/p_4w6rzeuz9dfi/chats/c_1c32d12a2747.jsonl
```

If git-ignored: no commit needed (just record that the local workspace is clean). If tracked: commit the cleanup separately.

This task has no commit unless the workspace is tracked.

---

### Task 9: End-to-end integration — agent /publish flow leaves no plaintext

**Files:**
- Create: `backend/tests/integration/test_publish_no_plaintext_leak.py`

- [ ] **Step 1: Test**

```python
"""Real-LLM smoke: drive a full /publish through ChatService and assert no
plaintext API keys land in the persisted chat jsonl. SSE side may still carry
plaintext (frontend reveal modal).
"""
import json
import os
import re
import pytest
from pathlib import Path

_EK_RE = re.compile(r"ek_[A-Za-z0-9_-]{32}")


@pytest.mark.asyncio
async def test_publish_flow_no_plaintext_in_jsonl(tmp_path: Path) -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("real-LLM test")
    # Seed: project + 3 reviewed docs above F1 threshold + schema. Reuse the
    # e2e_seed pattern from backend/tests/e2e_seed.py.
    # ...assemble seed with three reviewed docs that match predictions...

    from app.chat.service import ChatService
    from app.provider import build_provider

    svc = ChatService(workspace=tmp_path, provider=build_provider("anthropic"))
    sse_chunks: list[str] = []
    async for chunk in svc.chat_turn(
        project_id=pid, chat_id="c_publish",
        user_message="/publish",
    ):
        sse_chunks.append(chunk)

    # The SSE side IS allowed to carry plaintext (modal reveal).
    sse_blob = "\n".join(sse_chunks)
    assert _EK_RE.search(sse_blob), "expected SSE to carry plaintext for the modal"

    # The persisted jsonl side MUST NOT carry plaintext.
    log_path = tmp_path / "workspace" / pid / "chats" / "c_publish.jsonl"
    log_text = log_path.read_text()
    matches = _EK_RE.findall(log_text)
    assert not matches, f"plaintext API keys leaked into jsonl: {matches}"
```

This test depends on Task 5+6 redaction being in place AND on the agent successfully reaching `/publish` with the seeded fixtures. If seed fixtures are too tedious to assemble inline, factor a helper out of `backend/tests/e2e_seed.py`.

- [ ] **Step 2: Run + commit**

```bash
cd backend && ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY uv run pytest tests/integration/test_publish_no_plaintext_leak.py -v
git add backend/tests/integration/test_publish_no_plaintext_leak.py
git -c commit.gpgsign=false commit -m "test(secrets): /publish flow leaves no plaintext API key in jsonl"
```

---

## Wrap-up

### Task 10: Final acceptance + ROADMAP

- [ ] **Step 1: Tests green**

```bash
cd backend && uv run pytest -q
cd frontend && npm test
```

Expected: backend 295+ PASS, frontend 105 PASS (no frontend changes in M6).

- [ ] **Step 2: Update ROADMAP**

Flip M6 row to ✅ shipped + commit range. Strike-through both follow-ups (the 🚨 critical sandbox one and the M3-era plaintext API key one) under "Open cross-cutting follow-ups" with "(M6)" tags.

- [ ] **Step 3: Final commit**

```bash
git add docs/superpowers/plans/ROADMAP.md
git -c commit.gpgsign=false commit -m "docs(roadmap): mark M6 shipped + close 2 follow-ups"
```

---

## Out of scope for M6

- **Per-tool retry endpoint** — separate UX feature, not security
- **`_keys.json` workspace-wide flock** — multi-tenant prep, deferred
- **`/v1/{pid}/extract` audit log** — separate observability concern
- **Export bundle non-ASCII filename** — UX polish, not security
- **Extract path emitting `_evidence`** — unlocks click-to-page for real data; provider-adapter scope, separate milestone
