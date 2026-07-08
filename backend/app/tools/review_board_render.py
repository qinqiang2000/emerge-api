"""审单核对白板（review board）渲染核心 — A 方案（2026-07-04 plan）。

给**结构化/文本文档**（审单 JSON）产出「核对表」白板：不是页图圈注（文本 doc 无
光栅），而是 audit 白板「原件 + 圈注」哲学在结构化数据上的等价物——两张**原始表格**
（采购发票明细 + 结算细单）横排，数量核对不过的商品组在两表中以红框行 + 同号徽章
跨表呼应。审核员看的是原始数据，不是衍生核对表。

数据链路（纯计算，0 LLM）：每单来自两个文件——
- ``docs/审核数据_{id}.json``：``发票主信息`` / ``采购发票明细行`` / ``结算明细行`` /
  ``程序预计算.商品组配对明细``（数量规则）或 ``按商品分组的更价行分析``（更价规则）
  ——哪个组不合规 + 细单ID，用于定位高亮行。
- ``predictions/_draft/{filename}.json``：``entities[0].pass`` → verdict，
  ``entities[0].reason`` → 理由行，``entities[0].issues[].product`` → 问题商品交叉验证。

红线遵守：
- 无坐标——纯表格行高亮（`hit`/`qty-hit` class + 徽章），坐标概念不存在于此。
- 文档内容是不可信数据 → 所有文本值经 ``html.escape`` 才进 HTML。
- UI chrome 任务类型无关：本模块产 HTML 用通用「核对白板」措辞，措辞里保留业务表头
  （发票/结算是数据字段名，不是 UI chrome 动词）。
- HTML **不进 tool text 返回**（体积大 + 对 agent 无意义）；只走 HTTP 给前端 iframe。
"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any, Optional

from app.workspace.paths import docs_dir, prediction_draft_path

# ── 明暗双主题 + token 语系（取自审单白板原型 v2，裁掉 legend/aux/footer 用不到的）──
#
# 配色沿用 emerge token 语系 paper/ink/ochre/rose/moss，明暗靠 prefers-color-scheme
# 自动切换（board 全屏也可由 data-theme 强制，此处只保证独立打开即正确）。数字列
# tabular-nums 等宽。两张原始表 flex 横排，各自 overflow-x:auto——不整页滚动。
_BOARD_CSS = """
:root {
  --paper: #f7f4ee; --card: #fffdf9; --ink: #2a2520; --ink-2: #6f665c;
  --line: #e4ddd1; --line-soft: #efe9df; --thead: #f2ede4;
  --ochre: #a06b1c; --moss: #4d6b3f; --moss-bg: #eef2e6;
  --rose: #a33a33; --rose-bg: #f9ecea; --rose-line: #d9968f;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #1b1815; --card: #242019; --ink: #e9e2d6; --ink-2: #a1968a;
    --line: #3a342b; --line-soft: #2e2922; --thead: #2b2620;
    --ochre: #d5a04a; --moss: #9dbd85; --moss-bg: #28301f;
    --rose: #e08a7f; --rose-bg: #37231f; --rose-line: #7a4a42;
  }
}
:root[data-theme="light"] {
  --paper: #f7f4ee; --card: #fffdf9; --ink: #2a2520; --ink-2: #6f665c;
  --line: #e4ddd1; --line-soft: #efe9df; --thead: #f2ede4;
  --ochre: #a06b1c; --moss: #4d6b3f; --moss-bg: #eef2e6;
  --rose: #a33a33; --rose-bg: #f9ecea; --rose-line: #d9968f;
}
:root[data-theme="dark"] {
  --paper: #1b1815; --card: #242019; --ink: #e9e2d6; --ink-2: #a1968a;
  --line: #3a342b; --line-soft: #2e2922; --thead: #2b2620;
  --ochre: #d5a04a; --moss: #9dbd85; --moss-bg: #28301f;
  --rose: #e08a7f; --rose-bg: #37231f; --rose-line: #7a4a42;
}
* { box-sizing: border-box; }
body {
  background: var(--paper); color: var(--ink);
  font: 14.5px/1.6 -apple-system, "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
  margin: 0; padding: 24px 22px 40px;
}
.mono, .num { font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace; font-variant-numeric: tabular-nums; }
.head { display: flex; gap: 16px; align-items: flex-start; }
.stamp { flex: none; font-size: 17px; font-weight: 800; letter-spacing: .35em; text-indent: .35em;
  padding: 8px 6px 8px 10px; border: 2.5px solid currentColor; border-radius: 6px;
  transform: rotate(-4deg); margin-top: 2px; user-select: none; }
.stamp.fail { color: var(--rose); background: var(--rose-bg); }
.stamp.pass { color: var(--moss); background: var(--moss-bg); }
.head-main { min-width: 0; }
.head-main h2 { margin: 0; font-size: 17px; font-weight: 700; }
.head-main .meta { margin: 3px 0 0; color: var(--ink-2); font-size: 12.5px; }
.reason { margin: 14px 0 0; padding: 9px 14px; border-left: 3px solid var(--moss); background: var(--moss-bg); border-radius: 0 4px 4px 0; font-size: 14px; }
.reason.fail { border-left-color: var(--rose); background: var(--rose-bg); }
/* 「只看问题行」纯 CSS 开关（无脚本 — iframe sandbox=allow-forms 即可）:勾选后
   隐藏两表中非红框(.hit)的 tbody 行,审核员一键聚焦问题商品组。checkbox 视觉隐藏
   但保留可及性 + :checked;label 做成药丸开关。仅驳回单(有问题行)注入。 */
.hitonly { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.hitbar { margin: 14px 0 0; }
.hitbar label { display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px;
  color: var(--ink-2); cursor: pointer; user-select: none; padding: 4px 11px;
  border: 1px solid var(--line); border-radius: 999px; }
.hitbar label::before { content: ""; width: 13px; height: 13px; border-radius: 3px;
  border: 1.5px solid var(--ink-2); display: inline-block; flex: none; }
.hitonly:checked ~ .hitbar label { color: var(--rose); border-color: var(--rose-line); background: var(--rose-bg); }
.hitonly:checked ~ .hitbar label::before { background: var(--rose); border-color: var(--rose); }
.hitonly:focus-visible ~ .hitbar label { outline: 2px solid var(--ochre); outline-offset: 2px; }
.hitonly:checked ~ .tables tbody tr:not(.hit) { display: none; }
.tables { display: flex; flex-direction: column; gap: 20px; margin-top: 18px; }
.tcol { min-width: 0; }
.tbl-title { margin: 0 0 6px; font-size: 13.5px; font-weight: 700; }
.tbl-title .cnt { color: var(--ink-2); font-weight: 400; font-size: 12px; margin-left: 8px; }
.tbl-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 4px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th { text-align: left; font-weight: 600; font-size: 11.5px; color: var(--ink-2); letter-spacing: .05em;
  padding: 6px 10px; background: var(--thead); border-bottom: 1px solid var(--line); white-space: nowrap;
  position: sticky; top: 0; }
td { padding: 6px 10px; border-bottom: 1px solid var(--line-soft); white-space: nowrap; }
tbody tr:last-child td { border-bottom: none; }
tr.hit td { background: var(--rose-bg); border-top: 1.5px solid var(--rose-line); border-bottom: 1.5px solid var(--rose-line); }
tr.hit td:first-child { border-left: 3px solid var(--rose); font-weight: 600; }
td.qty-hit { color: var(--rose); font-weight: 700; }
.badge { display: inline-flex; align-items: center; justify-content: center; flex: none;
  min-width: 18px; height: 18px; border-radius: 50%; background: var(--rose); color: #fff;
  font-size: 11.5px; font-weight: 700; margin-right: 7px; font-family: ui-monospace, Menlo, monospace; }
:focus-visible { outline: 2px solid var(--ochre); outline-offset: 2px; }
"""

# 发票原始表列：(表头, 行字段 key, 是否数字列)。次序保留原型「原始行序与字段」。
_INV_COLS: list[tuple[str, str, bool]] = [
    ("货物或应税劳务名称", "发票货物或应税劳务名称", False),
    ("规格型号", "发票规格型号", False),
    ("单位", "发票商品单位", False),
    ("数量", "发票商品数量", True),
    ("含税单价", "发票含税单价", True),
    ("含税金额", "发票含税金额", True),
    ("税率", "发票税率", True),
    ("细单ID", "采购发票细单ID", True),
]
# 结算原始表列。
_DTL_COLS: list[tuple[str, str, bool]] = [
    ("商品名称", "商品名称(GOODSNAME)", False),
    ("规格", "规格(GOODSTYPE)", False),
    ("单位", "单位(GOODSUNIT)", False),
    ("数量", "数量(GOODSQTY)", True),
    ("单价", "单价(UNITPRICE)", True),
    ("行金额(含税)", "行金额(含税)(TOTAL_LINE)", True),
    ("行类别", "行类别(ZX_LINETYPENAME)", False),
    ("备注", "备注(MEMO)", False),
    ("细单ID", "结算细单ID(SUSETDTLID)", True),
]

_PROBLEM_GROUPS_KEY = "商品组配对明细(同一商品的结算多行已合并求和)"
# 更价规则(R-REPRICE-PAIR)数据文件的预计算形态：问题组 = 更价行不成对（一正一负
# 且数量净额为0 = False）。更价行只存在于结算细单，发票侧无对应行可框。
# v2 起首选「更价事件分析」（按采购细单.SUREPRICEDTLID 更价事件分组，确定性配对键）；
# 「按商品分组的更价行分析」是无采购数据时的退路键，两者条目形状相同。
_REPRICE_GROUPS_KEYS = (
    "更价事件分析(按SUREPRICEDTLID分组)",
    "按商品分组的更价行分析",
)


def _trim_num(v: Any) -> str:
    """数值尾零修剪（原型 footer「数值尾零已修剪」）：280.0→280，2.750→2.75，
    非数字/空原样返回字符串。规格里的量级不动（那是文本列）。"""
    if v is None or v == "":
        return ""
    if isinstance(v, bool):  # bool 是 int 子类，先挡掉
        return str(v)
    if isinstance(v, (int, float)):
        f = float(v)
        if not math.isfinite(f):  # NaN / inf（空折让行等）→ 空串
            return ""
        if f == int(f):
            return str(int(f))
        return ("%f" % f).rstrip("0").rstrip(".")
    s = str(v).strip()
    # 结算侧数字来自 CSV 常是字符串 "100.000000" / "61.2000000000"
    try:
        f = float(s)
        if not math.isfinite(f):
            return s
        if f == int(f):
            return str(int(f))
        return ("%f" % f).rstrip("0").rstrip(".")
    except (ValueError, TypeError):
        return s


def _text(v: Any) -> str:
    """文本列取值：None / float NaN → 空串（空折让行的规格/单位字段常是 NaN，
    直接 str() 会渲染成字面 "nan"）。其余原样转字符串。"""
    if v is None:
        return ""
    if isinstance(v, float) and not math.isfinite(v):
        return ""
    return str(v)


def _sid(v: Any) -> str:
    """细单ID 规范化为 str 用于跨侧比较（发票侧 int、结算侧 str）。"""
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def _problem_groups(
    precalc: dict[str, Any], issue_products: Optional[list[str]] = None,
) -> list[tuple[str, list[Any], list[Any]]]:
    """问题商品组 → (商品名, 发票侧细单IDs, 结算侧细单IDs)，保留预计算里的次序
    （= 徽章编号 1-based 依据）。规则无关的归一化层：每种规则的数据文件预计算
    形态不同，这里各认各的键，新规则加新分支即可，渲染层其余部分零改动。

    ``issue_products``（模型 entities[0].issues[].product）用于交叉验证：问题行
    = **导致驳回**的行。预计算里的结构异常若被规则的豁免分支放过（规格换算成立、
    备注已引用对应发票号），不该顶着红框出现在通过单上。传了非空 issue_products
    就只保留商品名能对上的组；全对不上时退回不过滤（宁可多框，别丢高亮）。"""
    out: list[tuple[str, list[Any], list[Any]]] = []
    groups = precalc.get(_PROBLEM_GROUPS_KEY)
    if isinstance(groups, list):
        for g in groups:
            if isinstance(g, dict) and g.get("数量合计一致") is False:
                out.append((
                    str(g.get("商品") or ""),
                    (g.get("发票侧") or {}).get("细单ID") or [],
                    (g.get("结算侧") or {}).get("细单ID") or [],
                ))
    for key in _REPRICE_GROUPS_KEYS:
        groups = precalc.get(key)
        if not isinstance(groups, list):
            continue
        for g in groups:
            if isinstance(g, dict) and g.get("一正一负且数量净额为0") is False:
                out.append((
                    str(g.get("商品") or ""),
                    [],
                    [r.get("细单ID") for r in (g.get("更价行明细") or [])
                     if isinstance(r, dict)],
                ))
        break  # 首个存在的键生效，事件键与商品键不叠加
    if issue_products:
        hit = [
            t for t in out
            if t[0] and any(t[0] in p or p in t[0] for p in issue_products if p)
        ]
        if hit:
            out = hit
    return out


def _hit_maps(
    problem_groups: list[tuple[str, list[Any], list[Any]]],
) -> tuple[dict[str, int], dict[str, int]]:
    """问题组 → {细单ID(str): 徽章号} 映射，发票侧 / 结算侧各一。"""
    inv_badge: dict[str, int] = {}
    dtl_badge: dict[str, int] = {}
    for n, (_name, inv_sids, dtl_sids) in enumerate(problem_groups, start=1):
        for sid in inv_sids:
            inv_badge[_sid(sid)] = n
        for sid in dtl_sids:
            dtl_badge[_sid(sid)] = n
    return inv_badge, dtl_badge


def _render_table(
    rows: list[dict[str, Any]],
    cols: list[tuple[str, str, bool]],
    id_key: str,
    badge_by_id: dict[str, int],
    qty_key: str,
) -> str:
    """一张原始表：保留原始行序与字段值；问题行标 hit + 首列徽章，数量单元格 qty-hit。"""
    head = "".join(f"<th>{html.escape(t)}</th>" for t, _, _ in cols)
    body_rows: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        badge = badge_by_id.get(_sid(row.get(id_key)))
        tr_cls = ' class="hit"' if badge else ""
        cells: list[str] = []
        for ci, (_, key, is_num) in enumerate(cols):
            val = _trim_num(row.get(key)) if is_num else _text(row.get(key))
            td_cls = "num" if is_num else ""
            if badge and key == qty_key:
                td_cls = (td_cls + " qty-hit").strip()
            prefix = ""
            if ci == 0 and badge:
                prefix = f'<span class="badge">{badge}</span>'
            cls_attr = f' class="{td_cls}"' if td_cls else ""
            cells.append(f"<td{cls_attr}>{prefix}{html.escape(val)}</td>")
        body_rows.append(f"<tr{tr_cls}>{''.join(cells)}</tr>")
    return (
        f'<div class="tbl-wrap"><table><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody></table></div>'
    )


def _doc_summary(
    doc_json: dict[str, Any], pred_json: dict[str, Any],
) -> dict[str, Any]:
    """单头摘要（供 board 左栏列表 + chat 卡片用）。"""
    info = doc_json.get("发票主信息") or {}
    ent = ((pred_json.get("entities") or [{}])[0]) or {}
    passed = ent.get("pass")
    verdict = "pass" if passed is True else "fail" if passed is False else "unclear"
    doc_id = str(
        doc_json.get("结算总单ID")
        or info.get("结算总单ID(SUSETDOCID)")
        or ""
    )
    return {
        "id": doc_id,
        "verdict": verdict,
        "supplier": str(info.get("供应商名称(SUPPLYNAME)") or ""),
        "amount": _trim_num(info.get("含税总金额(TOTAL_IN)")),
        "invoice_no": str(info.get("金税发票号码(GOLDTAXINVOICENUM)") or ""),
        "memo": str(info.get("总单备注(MEMO)") or ""),
        "reason": str(ent.get("reason") or ""),
        "issue_products": [
            str(i.get("product") or "")
            for i in (ent.get("issues") or [])
            if isinstance(i, dict)
        ],
    }


def _build_doc_html(summary: dict[str, Any], doc_json: dict[str, Any]) -> str:
    """一单的自包含 HTML（精简版，用户拍板）：印章 chip + 单头一行 + reason 一行 +
    横排两张原始表。去掉原型的 legend 长篇 / 程序核对摘要折叠 / footer。"""
    verdict = summary["verdict"]
    stamp_cls = "pass" if verdict == "pass" else "fail"
    stamp_txt = "通过" if verdict == "pass" else "驳回"
    reason_cls = "" if verdict == "pass" else " fail"

    meta_bits = []
    if summary["supplier"]:
        meta_bits.append(html.escape(summary["supplier"]))
    if summary["amount"]:
        meta_bits.append(f'含税 <span class="mono">{html.escape(summary["amount"])}</span> 元')
    if summary["invoice_no"]:
        meta_bits.append(f'发票 <span class="mono">{html.escape(summary["invoice_no"])}</span>')
    if summary["memo"]:
        meta_bits.append(f'总单备注「{html.escape(summary["memo"])}」')
    meta = " · ".join(meta_bits)

    reason_html = ""
    if summary["reason"]:
        reason_html = f'<p class="reason{reason_cls}">{html.escape(summary["reason"])}</p>'

    precalc = doc_json.get("程序预计算") or {}
    # 问题行 = 导致驳回的行：通过单不标（结构异常已被规则豁免分支解释，红框只会
    # 让「通过」印章显得自相矛盾）；驳回单用模型 issues 的商品名交叉验证后再框。
    problem_groups = (
        _problem_groups(precalc, summary.get("issue_products"))
        if verdict == "fail" else []
    )
    inv_badge, dtl_badge = _hit_maps(problem_groups)

    inv_rows = doc_json.get("采购发票明细行") or []
    dtl_rows = doc_json.get("结算明细行") or []
    inv_tbl = _render_table(inv_rows, _INV_COLS, "采购发票细单ID", inv_badge, "发票商品数量")
    dtl_tbl = _render_table(dtl_rows, _DTL_COLS, "结算细单ID(SUSETDTLID)", dtl_badge, "数量(GOODSQTY)")

    doc_id = html.escape(summary["id"])
    # 「只看问题行」开关——仅当存在问题商品组(驳回单)才注入;checkbox + label 必须
    # 作为 .tables 的前置兄弟节点,:checked ~ .tables 选择器才生效。
    n_hit = len(inv_badge) + len(dtl_badge)
    hit_toggle = ""
    if problem_groups:
        hit_toggle = (
            '<input type="checkbox" id="hitonly" class="hitonly">'
            '<div class="hitbar"><label for="hitonly">'
            f'只看问题行（{n_hit}）</label></div>'
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<style>{_BOARD_CSS}</style></head><body>"
        '<header class="head">'
        f'<span class="stamp {stamp_cls}">{stamp_txt}</span>'
        '<div class="head-main">'
        f'<h2>结算总单 <span class="mono">{doc_id}</span></h2>'
        f'<p class="meta">{meta}</p>'
        "</div></header>"
        f"{reason_html}"
        f"{hit_toggle}"
        '<div class="tables">'
        f'<div class="tcol"><h3 class="tbl-title">采购发票明细 '
        f'<span class="cnt">{len(inv_rows)} 行</span></h3>{inv_tbl}</div>'
        f'<div class="tcol"><h3 class="tbl-title">结算细单 '
        f'<span class="cnt">{len(dtl_rows)} 行</span></h3>{dtl_tbl}</div>'
        "</div></body></html>"
    )


def _load_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _model_label(pred_json: dict[str, Any]) -> str:
    run = pred_json.get("_run") or {}
    return str(run.get("model_label") or run.get("extract_model") or "")


async def render_review_board(workspace: Path, slug: str) -> dict[str, Any]:
    """读 docs/*.json + predictions/_draft/*.json，逐单拼自包含核对白板 HTML。

    返回::

        {
          "docs": [{id, verdict, supplier, amount, invoice_no, memo, reason}],
          "html_by_id": {id: 自包含 HTML 字符串},
          "tally": {"pass": n, "fail": m, "unclear": k},
          "model_label": str,
        }

    0 LLM——全部纯计算。无预测草稿的 doc 跳过（不产 card，与 board 的「只渲染有
    结果的单」一致）。docs 按文件名排序稳定输出。"""
    ddir = docs_dir(workspace, slug)
    docs: list[dict[str, Any]] = []
    html_by_id: dict[str, str] = {}
    tally = {"pass": 0, "fail": 0, "unclear": 0}
    model_label = ""

    doc_files = sorted(ddir.glob("*.json")) if ddir.is_dir() else []
    for dpath in doc_files:
        doc_json = _load_json(dpath)
        if doc_json is None:
            continue
        pred_json = _load_json(prediction_draft_path(workspace, slug, dpath.name))
        if pred_json is None:
            continue  # 无预测 → 跳过（没有审核结果的单不上白板）
        summary = _doc_summary(doc_json, pred_json)
        if not summary["id"]:
            continue
        docs.append(summary)
        html_by_id[summary["id"]] = _build_doc_html(summary, doc_json)
        tally[summary["verdict"]] = tally.get(summary["verdict"], 0) + 1
        if not model_label:
            model_label = _model_label(pred_json)

    return {
        "docs": docs,
        "html_by_id": html_by_id,
        "tally": tally,
        "model_label": model_label,
    }
