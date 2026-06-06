"""HTTP control surface for the LLM monitor — `/lab/monitor/*`.

Same dual-channel auth as the rest of `/lab/*` (`bind_workspace` enforces login
in tenant mode, headless reaches it with a Bearer PAT), so the monitor is fully
operable from Claude Code / curl — not just a UI button ([[同事精神]]). The
monitor itself is process-global (not team-scoped); `bind_workspace` here is the
auth gate, its workspace result is unused.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.auth.deps import bind_workspace
from app.monitor.monitor import get_monitor

router = APIRouter(prefix="/lab/monitor", dependencies=[Depends(bind_workspace)])


@router.get("")
@router.get("/status")
async def monitor_status() -> dict:
    return get_monitor().status_dict()


@router.post("/start")
async def monitor_start() -> dict:
    monitor = get_monitor()
    started = await monitor.start()
    return {"running": monitor.running, "started": started}


@router.post("/stop")
async def monitor_stop() -> dict:
    monitor = get_monitor()
    stopped = await monitor.stop()
    return {"running": monitor.running, "stopped": stopped}


@router.post("/check")
async def monitor_check() -> dict:
    """Run one probe sweep right now (on-demand health check) and return results
    plus the updated per-target state."""
    monitor = get_monitor()
    results = await monitor.sweep()
    return {
        "results": {name: asdict(res) for name, res in results.items()},
        "status": monitor.status_dict(),
    }


@router.post("/test-alert")
async def monitor_test_alert() -> dict:
    """Fire a test alert through the 云之家 webhook to verify the channel."""
    res = await get_monitor().send_test_alert()
    return {"ok": res.ok, "reason": res.reason(), **asdict(res)}
