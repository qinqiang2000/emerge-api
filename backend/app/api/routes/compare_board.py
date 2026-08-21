"""对比报告白板 render 路由（2026-08-20 compare-for-pm plan §3.2）。

GET /lab/projects/{slug}/compare/board-render?a=<ts>&b=<ts>

`render_board(kind='compare')` 的 HTTP 孪生（tool↔HTTP 对称，CLAUDE.md）：读两次
eval 的 `metrics/eval_<ts>/summary.json`，产一份自含 HTML 的对比报告，返回
``{headline, verdict, a_label, b_label, overall, per_field, html}``。0 LLM——纯计算。

`a` = 在位（baseline），`b` = 挑战者，与 `/projects/<slug>/eval/compare?a=&b=` 同向。

红线：`verdict` 不是装饰——`noise` 表示差距没跨过双阈值，前端不得把挑战者渲染成
赢家；报告文本经 ``html.escape`` 才进 HTML；前端 iframe srcdoc 渲染 ``html``。
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.routes._safety import safe_slug
from app.auth.deps import bind_workspace, current_ws
from app.tools.compare_board_render import CompareError, render_compare_board

router = APIRouter(dependencies=[Depends(bind_workspace)])

# 两种合法 handle（见 `compare_board_render.is_eval_ts`）：
#   - eval ts（与 `routes/eval.py::_TS_RE` 同形，不含 `latest` —— 本路由不解析
#     别名，skill 传的一律是 `score` / `run_experiment_eval` 返回的具体 ts）
#   - prediction source：`_draft` 或实验 id `ex_…`（没有 GT 时的分歧裁决态）
# query 参数是不可信输入，先按形状挡一道再进文件系统（INSIGHTS #8 同一条口径）。
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:-\d{1,2})?Z$")
_SOURCE_RE = re.compile(r"^(_draft|ex_[a-z0-9]{12})$")


def _validate_handle(v: str, which: str) -> None:
    if not (_TS_RE.match(v or "") or _SOURCE_RE.match(v or "")):
        raise HTTPException(status_code=400, detail={
            "error_code": "invalid_compare_handle",
            "error_message_en": (
                f"{which} is neither an eval timestamp nor a prediction "
                f"source (_draft / ex_…): {v!r}"
            ),
        })


@router.get("/lab/projects/{slug}/compare/board-render")
async def get_compare_board_render(
    slug: str,
    a: str = Query(..., description="incumbent eval ts, or a prediction source"),
    b: str = Query(..., description="challenger eval ts, or a prediction source"),
) -> dict:
    """对比报告：一次比较一份自含 HTML（不像审单白板那样逐单一份）。"""
    safe_slug(slug)
    _validate_handle(a, "a")
    _validate_handle(b, "b")
    try:
        return await render_compare_board(current_ws(), slug, a, b)
    except CompareError as e:
        raise HTTPException(status_code=404, detail={
            "error_code": e.error_code,
            "error_message_en": e.error_message_en,
        }) from e
