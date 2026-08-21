"""无 GT 时的分歧清单（2026-08-20 compare-for-pm plan §4 T9）。

产品经理拿一个**新项目**对比两个模型时，`reviewed/` 通常是空的。没有 ground
truth 就**没有准确率**——两侧的一致率不是准确率（HANDOFF「判断陷阱 1」，本项目
第一版就栽在这）。此时唯一诚实的产物是「哪些格子有分歧」，也就是一份**待裁决
工作清单**（造 GT 的过程本身）；裁完落 `save_reviewed` 才回到打分。

所以本模块的红线：**永不返回任何百分比 / 分数 / 一致率 / accuracy**。返回的只有
计数和格子本身。`tests/unit/test_diff_predictions.py::test_result_carries_no_score_keys`
把这条锁死。

复用而非重写：
- 等价判定走 `app/eval/normalize.py::normalize_equivalent` —— 数字 / 日期 / NFKC /
  array-of-object 的等价写法已经在那里吃掉了（`1,234.00` vs `1234` 不是分歧）。
- 缺席判定走 `app/eval/presence.py::is_absent` —— 与打分器同一份 lenient/strict 口径，
  两侧都留空不算分歧。
0 LLM——纯计算。

实体数不一致时按重叠部分对齐，并在 `entity_count_mismatch` 里**显式报出来**：曾有
模型在某些文档上实体切分失败（GT 3 个实体它只给 1 个），静默按重叠对齐会系统性
偏袒那一方。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from app.eval.normalize import normalize_equivalent
from app.eval.presence import (
    DEFAULT_PROJECT_POLICY,
    AbsentPolicy,
    is_absent,
    resolve_policy,
)
from app.schemas.schema_field import SchemaField
from app.workspace.paths import (
    experiment_predictions_dir,
    predictions_draft_dir,
    project_json_path,
)


#: 两侧来源的既有约定：`_draft` 即 `predictions/_draft/`（与 `ground(tab=)` /
#: `/eval/compare?a=&b=` 同一套 handle），其余只接受实验 id。
DRAFT_SOURCE = "_draft"
_EXPERIMENT_ID_RE = re.compile(r"^ex_[a-z0-9]{12}$")


class DiffSourceError(Exception):
    """来源 / 前置条件失败，带稳定 error_code 走统一 envelope（同 AuditError）。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.error_message_en = message


def resolve_source_dir(workspace: Path, slug: str, source: str) -> Path:
    """`_draft` → `predictions/_draft/`；`ex_xxx` → `experiments/{id}/predictions/`。

    严格白名单，不做别的解释：`source` 直接进路径，`../` 之类必须在这里被挡住
    （HTTP query 参数是不可信输入，INSIGHTS #8 同一条口径）。"""
    if source == DRAFT_SOURCE:
        return predictions_draft_dir(workspace, slug)
    if _EXPERIMENT_ID_RE.match(source or ""):
        return experiment_predictions_dir(workspace, slug, source)
    raise DiffSourceError(
        "diff_source_invalid",
        f"unknown prediction source {source!r} — expected '_draft' "
        f"(predictions/_draft/) or an experiment id (ex_…)",
    )


def _load_entities(pd_path: Path) -> dict[str, list[Any]]:
    """`{filename: entities}`，键是 doc 文件名（`{filename}.json` 去掉后缀，与
    `app/eval/score.py::_load_pred_and_reviewed` 同一口径）。

    坏 / 半写的 blob 跳过而不是炸掉——一个文件损坏不该让整份清单不可用。"""
    out: dict[str, list[Any]] = {}
    if not pd_path.is_dir():
        return out
    for p in sorted(pd_path.glob("*.json")):
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        ents = blob.get("entities") if isinstance(blob, dict) else None
        out[p.stem] = ents if isinstance(ents, list) else []
    return out


def _cell_value(v: Any) -> Optional[str]:
    """格子里的原样值。留空的一侧给 None；非字符串（数组/对象/数字）JSON 化。

    注意不把 `""` / `"n/a"` 归一成 None——裁决人要看见对面到底写了什么。"""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


async def diff_predictions(
    workspace: Path,
    slug: str,
    a: str,
    b: str,
    *,
    project_policy: AbsentPolicy = DEFAULT_PROJECT_POLICY,
) -> dict[str, Any]:
    """逐 `(filename, entity_idx, field)` 对齐两侧预测，返回分歧清单。

    `a` / `b` 是两侧预测来源：``'_draft'`` 或实验 id（``ex_…``）。

    返回::

        {
          "n_cells": int,              # 对齐到的总格数（含两侧都留空的）
          "n_diff": int,               # 分歧格数
          "n_diff_required": int,      # 其中 SchemaField.required 字段的分歧数
          "by_field": [{"field", "n_diff", "required"}],   # 只列有分歧的字段
          "cells": [{"filename", "entity_idx", "field", "a", "b", "required"}],
          "entity_count_mismatch": [{"filename", "n_a", "n_b"}],
        }

    `cells` / `by_field` 都按「required 优先、同字段成簇」排序——裁决是按字段批量
    做的（「这些取 A」），重要字段的时间最该先花。

    **不返回任何比率**：无 GT 时一致率不是准确率，这是红线，不是口味。
    """
    from app.tools.schema import read_schema

    if not project_json_path(workspace, slug).exists():
        raise DiffSourceError("project_not_found", f"project {slug!r} not found")

    dirs = {"a": resolve_source_dir(workspace, slug, a),
            "b": resolve_source_dir(workspace, slug, b)}
    for side, source in (("a", a), ("b", b)):
        if not dirs[side].is_dir():
            raise DiffSourceError(
                "diff_source_not_found",
                f"prediction source {source!r} has no predictions directory "
                f"(nothing has been extracted into it yet)",
            )

    fields: list[SchemaField] = [
        f for f in await read_schema(workspace, slug) if f.name
    ]
    if not fields:
        raise DiffSourceError(
            "schema_not_found", f"project {slug!r} has no schema fields",
        )
    required_of = {str(f.name): bool(f.required) for f in fields}

    ents_a = _load_entities(dirs["a"])
    ents_b = _load_entities(dirs["b"])

    n_cells = 0
    cells: list[dict[str, Any]] = []
    n_diff_of: dict[str, int] = {str(f.name): 0 for f in fields}
    mismatch: list[dict[str, Any]] = []

    # 文件名取并集：只出现在一侧的 doc 自然表现为 n=0 vs n=k，落进
    # entity_count_mismatch 而不是被静默丢掉。
    for filename in sorted(set(ents_a) | set(ents_b)):
        ea = ents_a.get(filename) or []
        eb = ents_b.get(filename) or []
        if len(ea) != len(eb):
            mismatch.append({"filename": filename, "n_a": len(ea), "n_b": len(eb)})
        for entity_idx in range(min(len(ea), len(eb))):
            ent_a = ea[entity_idx] if isinstance(ea[entity_idx], dict) else {}
            ent_b = eb[entity_idx] if isinstance(eb[entity_idx], dict) else {}
            for field in fields:
                name = str(field.name)
                n_cells += 1
                va, vb = ent_a.get(name), ent_b.get(name)
                policy = resolve_policy(field, project_policy)
                a_absent, b_absent = is_absent(va, policy), is_absent(vb, policy)
                if a_absent and b_absent:
                    continue  # 两侧都说这里没值 —— 没有可裁决的东西
                if (
                    not a_absent
                    and not b_absent
                    and normalize_equivalent(va, vb, field).equivalent
                ):
                    continue  # 写法不同、值相同（1,234.00 ↔ 1234）
                n_diff_of[name] += 1
                cells.append({
                    "filename": filename,
                    "entity_idx": entity_idx,
                    "field": name,
                    "a": _cell_value(va),
                    "b": _cell_value(vb),
                    "required": required_of[name],
                })

    cells.sort(key=lambda c: (
        not c["required"], c["field"], c["filename"], c["entity_idx"],
    ))
    by_field = sorted(
        (
            {"field": name, "n_diff": n, "required": required_of[name]}
            for name, n in n_diff_of.items() if n
        ),
        key=lambda r: (not r["required"], -int(r["n_diff"]), str(r["field"])),
    )

    return {
        "n_cells": n_cells,
        "n_diff": len(cells),
        "n_diff_required": sum(1 for c in cells if c["required"]),
        "by_field": by_field,
        "cells": cells,
        "entity_count_mismatch": mismatch,
    }
