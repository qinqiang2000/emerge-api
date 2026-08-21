"""无 GT 分歧清单的 HTTP 孪生（2026-08-20 compare-for-pm plan §4 T9）。

GET /lab/projects/{slug}/compare/diff?a=&b=

``diff_predictions`` @tool 的 HTTP 形（tool ↔ HTTP ↔ MCP 三形对称，CLAUDE.md）：
逐 (filename, entity_idx, field) 对齐两侧预测，返回**分歧清单**——没有 ground
truth 的项目算不出准确率，两模型的一致率不是准确率，所以这个响应里没有、也不许
有任何百分比。全部聚合逻辑住在 `app.tools.diff_predictions` 这一份实现里，路由只
做 slug 校验 + 错误信封，保证两形对同一项目产出同一份 JSON。

`safe_slug` 先跑，攻击者提供的 slug（NUL / `..` / 斜杠）在任何文件系统读之前被
400 掉（INSIGHTS #8）；`a` / `b` 同样是不可信输入，由
`diff_predictions.resolve_source_dir` 白名单挡住（`_draft` 或 `ex_…`）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.routes._safety import safe_slug
from app.auth.deps import bind_workspace, current_ws
from app.tools.diff_predictions import DiffSourceError, diff_predictions


router = APIRouter(dependencies=[Depends(bind_workspace)])


@router.get("/lab/projects/{slug}/compare/diff")
async def get_compare_diff(slug: str, a: str, b: str) -> dict:
    """两侧预测的分歧清单。`a` / `b` 取 `_draft` 或实验 id（`ex_…`）。

    400 `diff_source_invalid`（来源名不认识）；404 `project_not_found` /
    `diff_source_not_found` / `schema_not_found`。"""
    safe_slug(slug)
    try:
        return await diff_predictions(current_ws(), slug, a, b)
    except DiffSourceError as e:
        raise HTTPException(
            status_code=400 if e.error_code == "diff_source_invalid" else 404,
            detail={
                "error_code": e.error_code,
                "error_message_en": e.error_message_en,
            },
        )
