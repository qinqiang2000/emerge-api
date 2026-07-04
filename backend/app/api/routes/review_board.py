"""审单核对白板 render 路由（2026-07-04 review-board plan）。

GET /lab/projects/{slug}/review/board-render
``render_review_board`` @tool 的 HTTP 孪生（tool↔HTTP 对称，CLAUDE.md）：读
docs/*.json + predictions/_draft/*.json，逐单拼自包含核对白板 HTML，返回
``{docs, html_by_id, tally, model_label}``。0 LLM——纯计算。

红线：无坐标（结构化数据的核对表是表格行高亮，坐标概念不存在于此）；文档内容经
``html.escape`` 才进 HTML；前端 iframe srcdoc 渲染 ``html_by_id[id]``。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.routes._safety import safe_slug
from app.auth.deps import bind_workspace, current_ws
from app.tools.review_board_render import render_review_board

router = APIRouter(dependencies=[Depends(bind_workspace)])


@router.get("/lab/projects/{slug}/review/board-render")
async def get_review_board_render(slug: str) -> dict:
    """逐单核对白板：每单一份自包含 HTML（左栏 select，右侧 iframe）。无预测草稿的
    doc 跳过——从不报错，只是不产 card（空项目 → docs 为空）。"""
    safe_slug(slug)
    return await render_review_board(current_ws(), slug)
