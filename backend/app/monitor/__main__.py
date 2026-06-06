"""Standalone CLI — run the monitor decoupled from the API process.

    python -m app.monitor run          # foreground loop (daemonize via systemd/&)
    python -m app.monitor once         # one sweep, print table, exit nonzero if any down
    python -m app.monitor test-alert   # fire a test 云之家 alert, verify the channel
    python -m app.monitor status       # print resolved config + targets (no probing)

`run`/`once` are also the natural fit for an external scheduler (cron/systemd
timer) if you'd rather not keep a long-lived process. Config comes entirely from
`backend/.env` + the environment (see MonitorConfig).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from app.monitor.config import MonitorConfig
from app.monitor.monitor import LLMMonitor


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _cmd_run(cfg: MonitorConfig) -> int:
    monitor = LLMMonitor(cfg)
    await monitor.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # e.g. Windows
            pass
    await stop.wait()
    await monitor.stop()
    return 0


async def _cmd_once(cfg: MonitorConfig) -> int:
    monitor = LLMMonitor(cfg)
    if not monitor.targets:
        print(
            "no probe targets — set GOOGLE_API_KEY / ANTHROPIC_API_KEY "
            "(or EMERGE_MONITOR_PROBE_AGENT=1) in backend/.env",
            file=sys.stderr,
        )
        return 2
    results = await monitor.sweep()
    bad = 0
    for name, res in results.items():
        flag = "OK  " if res.ok else "DOWN"
        tail = "" if res.ok else f"  — {res.error}"
        print(f"  [{flag}] {name:<10} {res.latency_ms:7.0f}ms{tail}")
        if not res.ok:
            bad += 1
    return 1 if bad else 0


async def _cmd_test_alert(cfg: MonitorConfig) -> int:
    monitor = LLMMonitor(cfg)
    res = await monitor.send_test_alert()
    if res.ok:
        print("云之家测试告警：发送成功 ✓")
        return 0
    print(f"云之家测试告警：发送失败 ✗ — {res.reason()}", file=sys.stderr)
    return 1


def _cmd_status(cfg: MonitorConfig) -> int:
    monitor = LLMMonitor(cfg)
    print("emerge LLM monitor — resolved config")
    print(f"  webhook configured : {'yes' if cfg.webhook_url else 'NO'}")
    print(f"  interval           : {cfg.interval:.0f}s")
    print(f"  probe timeout      : {cfg.probe_timeout:.0f}s")
    print(f"  fail threshold     : {cfg.fail_threshold}")
    print(f"  re-alert after     : {cfg.realert_after:.0f}s (0=once)")
    print(f"  host tag           : {cfg.host}")
    print(f"  google key present : {'yes' if cfg.google_api_key else 'no'}")
    print(f"  anthropic key pres.: {'yes' if cfg.anthropic_api_key else 'no'}")
    print(f"  probe agent brain  : {'yes' if cfg.probe_agent else 'no'}")
    if monitor.targets:
        print("  targets:")
        for t in monitor.targets:
            print(f"    - {t.name:<10} model={t.model_id or '-'}")
    else:
        print("  targets            : (none — no provider keys / agent probe)")
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(prog="python -m app.monitor")
    parser.add_argument(
        "command",
        choices=["run", "once", "test-alert", "status"],
        help="run=loop, once=single sweep, test-alert=verify 云之家, status=show config",
    )
    args = parser.parse_args(argv)
    cfg = MonitorConfig.from_env()

    if args.command == "status":
        return _cmd_status(cfg)
    if args.command == "run":
        return asyncio.run(_cmd_run(cfg))
    if args.command == "once":
        return asyncio.run(_cmd_once(cfg))
    if args.command == "test-alert":
        return asyncio.run(_cmd_test_alert(cfg))
    return 2  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
