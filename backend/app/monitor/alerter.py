"""云之家 (yunzhijia) webhook alerter.

A single POST of `{"content": "..."}` to the robot webhook. The *only* thing
the monitor fills is `content`; everything else (URL + yzjtoken) is config.

Response taxonomy (per the channel's contract):
  - HTTP 2xx + success=true + errorCode=0  → delivered.
  - HTTP 2xx + errorCode != 0              → business failure (bad token, rate
                                             limited, content rejected, …).
  - HTTP 4xx/5xx                           → network / server-side failure.
Anything that is not "delivered" is logged at ERROR as a *send-failure* alert
(so a broken alert channel is itself visible), and reported back via AlertResult
so callers/CLI can surface it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.monitor.config import scrub_secrets

log = logging.getLogger("emerge.monitor")


@dataclass
class AlertResult:
    ok: bool
    http_status: int | None = None
    error_code: int | None = None
    error_msg: str = ""
    transport_error: str = ""

    def reason(self) -> str:
        """One-line human reason for a non-OK result (CLI / API friendly)."""
        if self.ok:
            return "ok"
        if self.transport_error:
            return f"transport: {self.transport_error}"
        if self.http_status and self.http_status // 100 != 2:
            return f"http {self.http_status}: {self.error_msg}"
        return f"errorCode={self.error_code}: {self.error_msg}"


class YunzhijiaAlerter:
    def __init__(
        self,
        url: str,
        *,
        proxy: str | None = None,
        timeout: float = 10.0,
        secrets: tuple[str, ...] = (),
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = url
        self._proxy = proxy
        self._timeout = timeout
        self._secrets = tuple(secrets)
        # Injected only by tests (httpx.MockTransport); None in production.
        self._transport = transport

    async def send(self, content: str) -> AlertResult:
        # trust_env=False mirrors the provider adapters: never inherit the
        # agent-side CLAUDE_PROXY (SOCKS5) into this plain-internet POST.
        kwargs: dict = {"timeout": self._timeout, "trust_env": False}
        if self._proxy:
            kwargs["proxy"] = self._proxy
        if self._transport is not None:
            kwargs["transport"] = self._transport
        try:
            async with httpx.AsyncClient(**kwargs) as client:
                resp = await client.post(
                    self._url,
                    headers={"Content-Type": "application/json;charset=utf-8"},
                    json={"content": content},
                )
        except Exception as e:  # noqa: BLE001 — any transport blip is a send failure
            err = scrub_secrets(str(e) or type(e).__name__, self._secrets)
            log.error("发送云之家告警失败（网络/传输异常）：%s ｜ content=%s", err, content)
            return AlertResult(ok=False, transport_error=err)

        if resp.status_code // 100 != 2:
            body = scrub_secrets(resp.text[:300], self._secrets)
            log.error(
                "发送云之家告警失败（HTTP %s）：%s ｜ content=%s",
                resp.status_code, body, content,
            )
            return AlertResult(ok=False, http_status=resp.status_code, error_msg=body)

        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            body = scrub_secrets(resp.text[:300], self._secrets)
            log.error(
                "发送云之家告警失败（2xx 但响应非 JSON）：%s ｜ content=%s", body, content,
            )
            return AlertResult(
                ok=False, http_status=resp.status_code, error_msg="non-json response",
            )

        code = data.get("errorCode")
        success = data.get("success")
        if success is True and code in (0, None):
            log.info("云之家告警发送成功：%s", content)
            return AlertResult(ok=True, http_status=resp.status_code, error_code=0)

        msg = scrub_secrets(str(data.get("errorMsg", "")), self._secrets)
        log.error(
            "发送云之家告警失败（业务失败 errorCode=%s）：%s ｜ content=%s",
            code, msg, content,
        )
        return AlertResult(
            ok=False, http_status=resp.status_code, error_code=code, error_msg=msg,
        )
