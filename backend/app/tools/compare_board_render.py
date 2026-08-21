"""对比报告白板（compare board）渲染核心 — 2026-08-20 compare-for-pm plan §3.2。

`render_board` 的第三种介质。前两种是「原件上圈注」（kind='audit'，页图）与
「原始表格里高亮行」（kind='review'，结构化审单）；这一种的被观察对象不是某一份
文档，而是**两次 eval 之间的差**——所以它渲染的是数字，不是原件。

为什么要有它：模型对比的结论过去活在一次性脚本产的 HTML 里（用户 Desktop 的
`_workbench/make_report*.py`），产品里只有 chat 里的 markdown 表。表转不出去——
产品经理需要的是一个能直接发给别人的链接。

口径红线（`app/skills/domains/experiments.md` 的 `### 口径` 是同一套，改一处必须
改两处）：

- 头条是 **GT 有值格微平均**（`cell_accuracy_nonempty`），不是官方 macro。
  官方 macro 的 `(correct + absent_both) / total` 把「两边都空」算作预测正确，
  罕见字段天然接近 100% —— 它在报告里只能当脚注，且必须带上那句注解。
- **不报 `doc_accuracy`**（会出现「0 篇全对却 84.4%」的自相矛盾读数），
  用「整篇零错 n/N」代替。
- `accuracy_nonempty is None` 的字段渲染成 `n/a`，**绝不是 0%**。
- 判赢要**两个条件同时成立**（见 `_verdict`）。差距落在噪声带内时 headline 必须
  是「分不出高下」，不许把噪声包装成结论。

0 LLM —— 全部纯计算，只读 `metrics/eval_<ts>/summary.json`。
文本值（模型名、字段名）一律 `html.escape` 才进 HTML（同 review board 红线）。
HTML 不进 tool 的 text 返回，只走 HTTP 孪生给前端 iframe。
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Optional

from app.schemas.score import FieldScore, ScoreResultSummary
from app.workspace.paths import eval_cells_path, eval_summary_path, metrics_path

#: 两侧标识有两种合法形态，靠形状区分，不需要额外的 mode 参数：
#:   - eval ts（`2026-08-20T11-00-00Z`）→ 有 GT,出准确率报告
#:   - prediction source（`_draft` / `ex_…`）→ 没有 GT,出分歧裁决清单
#: 同一个问题的两种输入,不是两种语义。
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:-\d{1,2})?Z$")

#: 明细表最多渲染多少行。裁决是按字段批量做的，几百行明细一次铺开对人没有帮助，
#: 而且会把页面撑爆 —— 超出的部分让用户按字段回 chat 里要。
_MAX_DETAIL_ROWS = 300


def is_eval_ts(handle: str) -> bool:
    return bool(_TS_RE.match(handle or ""))

# ── 判据阈值（skill 的 `### 判据` 一节是同一套数）─────────────────────────
# 单轮跑批有噪声，小幅领先常常只是运气。两条同时成立才算赢：
_MIN_DELTA_CELLS = 3      # 有值格里多对的格数
_MIN_DELTA_PP = 9.0       # 有值格准确率的百分点差
#
# 为什么是「格数 + 百分点」两把尺：百分点随样本量缩放（19 篇里一格 ≈ 0.7pp，
# 200 篇里一格 ≈ 0.07pp），单看它会让小样本项目遍地「显著」；格数不随样本量
# 缩放，单看它会让大样本项目永远「显著」。两条同时卡住才两头都不塌。


class CompareError(Exception):
    """错误响应契约 `{error_code, error_message_en}`（CLAUDE.md）。"""

    def __init__(self, error_code: str, error_message_en: str) -> None:
        super().__init__(error_message_en)
        self.error_code = error_code
        self.error_message_en = error_message_en


def _load_summary(workspace: Path, slug: str, ts: str) -> ScoreResultSummary:
    """读一次 eval 的 summary。历史布局（`metrics/eval_<ts>.json` 单文件）仍能读
    —— 那些 blob 没有本模块要的新键，靠 pydantic 默认值兜住，落到「n/a」而不是 0%。"""
    p = eval_summary_path(workspace, slug, ts)
    if not p.exists():
        legacy = metrics_path(workspace, slug, f"eval_{ts}")
        if not legacy.exists():
            raise CompareError(
                "eval_not_found",
                f"no eval at {ts!r} for project {slug!r} — run score/run_experiment_eval first",
            )
        p = legacy
    try:
        return ScoreResultSummary(**json.loads(p.read_text(encoding="utf-8")))
    except Exception as e:  # noqa: BLE001 — 坏 blob 要给出可诊断的 error_code
        raise CompareError("eval_unreadable", f"could not parse eval {ts!r}: {e}") from e


def _side_label(s: ScoreResultSummary, ts: str) -> str:
    """人读的一侧名字。语义名优先于 id —— 报告是给产品经理看的，`ex_78r3…` 对她
    毫无意义（repo 惯例：chat 里说 `gemini-3-flash`，id 只留给 plan 与运维脚本）。"""
    parts = [p for p in (s.extract_model, s.prompt_label) if p]
    return " · ".join(parts) if parts else ts


def _nonempty_counts(f: FieldScore) -> tuple[int, int]:
    """(有值格里对的数, 有值格总数)。

    `FieldScore.correct` 里混着 `absent_both`（两边都说没有 —— 那是送分格），
    所以分子要先把它减掉；`spurious`（GT 空但模型填了）不进有值格分母。
    公式与 `FieldScore` 的 docstring 一致。"""
    num = f.correct - f.n_absent_both
    return num, num + f.n_wrong + f.n_missing


def _totals(summary: ScoreResultSummary, required_only: bool = False) -> tuple[int, int]:
    num = den = 0
    for f in summary.per_field:
        if required_only and not f.required:
            continue
        n, d = _nonempty_counts(f)
        num += n
        den += d
    return num, den


def _verdict(a: ScoreResultSummary, b: ScoreResultSummary) -> tuple[str, int, Optional[float]]:
    """返回 (verdict, Δ格数, Δpp)。verdict ∈ {'win', 'lose', 'noise'}。

    `win` 只在两条阈值都被跨过时给出。任何一条不满足都是 `noise` —— 调用方必须
    把它渲染成「分不出高下」，不许写成「略优」。

    `lose` 是同样两条线反过来：挑战者**明显更差**。这一态必须和 `noise` 分开 ——
    2026-08-21 dogfood 拿一个已知差很多的模型来比，得到的却是「分不出高下，维持
    现状」。维持现状这个动作没错，但那句话是错的，而人只会记住那句话。"""
    a_num, _ = _totals(a)
    b_num, _ = _totals(b)
    delta_cells = b_num - a_num

    delta_pp: Optional[float] = None
    if a.cell_accuracy_nonempty is not None and b.cell_accuracy_nonempty is not None:
        delta_pp = (b.cell_accuracy_nonempty - a.cell_accuracy_nonempty) * 100

    if delta_pp is not None and delta_cells > _MIN_DELTA_CELLS and delta_pp > _MIN_DELTA_PP:
        return "win", delta_cells, delta_pp
    if delta_pp is not None and delta_cells < -_MIN_DELTA_CELLS and delta_pp < -_MIN_DELTA_PP:
        return "lose", delta_cells, delta_pp
    return "noise", delta_cells, delta_pp


def _pct(v: Optional[float]) -> str:
    """`None` → `n/a`。GT 从来没有值的字段不是 0 分，是没考。"""
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _delta_str(a: Optional[float], b: Optional[float]) -> str:
    if a is None or b is None:
        return "—"
    d = (b - a) * 100
    return f"{d:+.1f}pp"


def _delta_sort_key(row: dict[str, Any]) -> float:
    a, b = row["a_acc"], row["b_acc"]
    if a is None or b is None:
        return -1.0  # 无法比较的排最后
    return abs(b - a)


# ── 明暗双主题，token 语系与 review board 同源（paper/ink/ochre/rose/moss）──
_CSS = """
:root {
  --paper: #f7f4ee; --card: #fffdf9; --ink: #2a2520; --ink-2: #6f665c;
  --line: #e4ddd1; --line-soft: #efe9df; --thead: #f2ede4;
  --ochre: #a06b1c; --ochre-bg: #f6efe1;
  --moss: #4d6b3f; --moss-bg: #eef2e6;
  --rose: #a33a33; --rose-bg: #f9ecea;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper: #1b1815; --card: #242019; --ink: #e9e2d6; --ink-2: #a1968a;
    --line: #3a342b; --line-soft: #2e2922; --thead: #2b2620;
    --ochre: #d5a04a; --ochre-bg: #332a1b;
    --moss: #9dbd85; --moss-bg: #28301f;
    --rose: #e08a7f; --rose-bg: #37231f;
  }
}
:root[data-theme="dark"] {
  --paper: #1b1815; --card: #242019; --ink: #e9e2d6; --ink-2: #a1968a;
  --line: #3a342b; --line-soft: #2e2922; --thead: #2b2620;
  --ochre: #d5a04a; --ochre-bg: #332a1b;
  --moss: #9dbd85; --moss-bg: #28301f;
  --rose: #e08a7f; --rose-bg: #37231f;
}
* { box-sizing: border-box; }
body {
  background: var(--paper); color: var(--ink); margin: 0; padding: 26px 24px 48px;
  font: 14.5px/1.65 -apple-system, "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
}
h1 { margin: 0 0 2px; font-size: 18px; font-weight: 700; }
.sub { margin: 0 0 20px; color: var(--ink-2); font-size: 12.5px; }
.verdict { margin: 0 0 22px; padding: 12px 16px; border-left: 3px solid var(--ochre);
  background: var(--ochre-bg); border-radius: 0 4px 4px 0; font-size: 15px; }
.verdict.win { border-left-color: var(--moss); background: var(--moss-bg); }
.verdict.noise { border-left-color: var(--ink-2); background: var(--card); }
.verdict.no_gt { border-left-color: var(--ochre); background: var(--ochre-bg); }
.verdict.lose { border-left-color: var(--rose); background: var(--rose-bg); }
.verdict.stale { border-left-color: var(--ochre); background: var(--ochre-bg); }
ul { margin: 6px 0 0; padding-left: 20px; color: var(--ink-2); font-size: 12.5px; }
h2 { margin: 26px 0 8px; font-size: 13.5px; font-weight: 700; letter-spacing: .04em; }
.wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 4px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th { text-align: left; font-weight: 600; font-size: 11.5px; color: var(--ink-2);
  letter-spacing: .05em; padding: 7px 11px; background: var(--thead);
  border-bottom: 1px solid var(--line); white-space: nowrap; }
td { padding: 7px 11px; border-bottom: 1px solid var(--line-soft); white-space: nowrap; }
/* 分歧明细的值列：一个长地址就能把对面那一列挤出视口，而并排对比正是这张表
   存在的理由。限宽 + 换行，宁可高也不能把对侧顶出去。 */
td.val { white-space: normal; word-break: break-word; max-width: 30ch;
  vertical-align: top; line-height: 1.45; }
td.doc { white-space: normal; word-break: break-word; max-width: 22ch;
  vertical-align: top; color: var(--ink-2); font-size: 12px; }
th.val, th.doc { white-space: nowrap; }
tbody tr:last-child td { border-bottom: none; }
.num { font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
  font-variant-numeric: tabular-nums; text-align: right; }
.up { color: var(--moss); font-weight: 600; }
.down { color: var(--rose); font-weight: 600; }
.na { color: var(--ink-2); }
tr.key td { font-weight: 600; }
tr.hard td:first-child::before { content: "★ "; color: var(--ochre); }
tr.hard td { font-weight: 600; }
tr.faint td { color: var(--ink-2); font-size: 12px; }
.foot { margin-top: 8px; color: var(--ink-2); font-size: 12px; }
details { margin-top: 10px; }
summary { cursor: pointer; color: var(--ink-2); font-size: 12.5px; }
.fjump { color: var(--ink); text-decoration: none; border-bottom: 1px dotted var(--ink-2); }
.fjump:hover { color: var(--ochre); border-bottom-color: var(--ochre); }
details.drill { margin: 0; border-bottom: 1px solid var(--line-soft); }
details.drill > summary { padding: 9px 4px; color: var(--ink); font-size: 13.5px;
  display: flex; align-items: baseline; gap: 9px; list-style: none; }
details.drill > summary::-webkit-details-marker { display: none; }
details.drill > summary::before { content: "▸"; color: var(--ink-2); font-size: 11px; }
details.drill[open] > summary::before { content: "▾"; }
details.drill[open] > summary { background: var(--thead); }
.dfield { font-weight: 600; }
.crit { color: var(--ochre); }
details.drill .wrap { border: none; border-radius: 0; margin: 0 0 10px 18px; }
details.drill td { border-bottom: 1px solid var(--line-soft); vertical-align: top; }
details.drill th { white-space: normal; }
details.drill table { table-layout: fixed; }
td.gt { color: var(--ink); font-weight: 600; }
td.doc { white-space: normal; word-break: break-word; max-width: 20ch; font-size: 12px; }
.kb { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 11px;
  white-space: nowrap; }
.kb.b-ok { background: var(--moss-bg); color: var(--moss); }
.kb.b-bad { background: var(--rose-bg); color: var(--rose); }
.doclink { color: var(--ochre); text-decoration: none; border-bottom: 1px solid transparent; }
.doclink:hover { border-bottom-color: var(--ochre); }
:focus-visible { outline: 2px solid var(--ochre); outline-offset: 2px; }
"""


def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


#: 格级判定的中文说法。报告的读者不读 `spurious` 这种词。
_STATUS_ZH = {
    "correct": "对",
    "wrong": "错值",
    "missing": "漏抽",
    "spurious": "多填",
    "absent_both": "都空",
}
#: 单元格里显示的值最长多少字符 —— 明细表要一眼扫，不是让人读全文。
_VALUE_CLIP = 90


def _load_cells(workspace: Path, slug: str, ts: str) -> dict[tuple[str, int, str], dict[str, Any]]:
    """`cells.jsonl` → `{(filename, entity_idx, field): cell}`。

    逐字段汇总只能回答「这个字段差多少」，回答不了「哪几篇、错成什么」——
    而那正是看到一行 `-16.7pp` 之后必然要问的下一个问题。缺了它，读的人只能
    回去翻原始数据，报告就断在这里。

    文件不在（历史 blob 只有 summary.json）时返回空 —— 明细区跟着消失，
    汇总照常。"""
    out: dict[tuple[str, int, str], dict[str, Any]] = {}
    p = eval_cells_path(workspace, slug, ts)
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            c = json.loads(line)
        except json.JSONDecodeError:
            continue  # 一行坏了不该让整个明细区消失
        key = (c.get("filename") or "", int(c.get("entity_idx") or 0), c.get("field") or "")
        out[key] = c
    return out


def _clip(v: Optional[str]) -> str:
    if v is None or v == "":
        return "∅ 留空"
    s = str(v)
    return s if len(s) <= _VALUE_CLIP else s[:_VALUE_CLIP] + "…"


def _ok_status(s: Optional[str]) -> bool:
    return s in ("correct", "absent_both")


def _build_drilldowns(
    a_cells: dict[tuple[str, int, str], dict[str, Any]],
    b_cells: dict[tuple[str, int, str], dict[str, Any]],
    per_field: list[dict[str, Any]],
    *,
    slug: str,
    base_url: str,
    a_label: str = "",
    b_label: str = "",
) -> tuple[dict[str, int], str]:
    """每个字段一个可折叠明细：**至少一侧判错**的格，逐格给出 GT 与两侧的值。

    返回 `({field: 有问题的格数}, html)`。前者让逐字段表决定哪些字段名做成
    可点的锚点 —— 没有问题格的字段点开是空的，不如不让点。

    文档名做成 `?review=<filename>` 的链接：看到某格错了，下一步一定是想看
    原件长什么样。链接带 `target="_blank"`（iframe 侧因此需要 allow-popups）。"""
    from urllib.parse import quote

    # 表头用短名：`gemini-2.5-flash · Baseline v3` 放进 6 列表格会把值列挤没。
    # 模型名是两侧唯一的区别（prompt 通常相同），截到它就够认人。
    a_name = (a_label.split(" · ")[0] or "A")
    b_name = (b_label.split(" · ")[0] or "B")

    keys = set(a_cells) | set(b_cells)
    by_field: dict[str, list[tuple[str, int, dict[str, Any], dict[str, Any]]]] = {}
    for k in keys:
        filename, entity_idx, field = k
        ca, cb = a_cells.get(k), b_cells.get(k)
        sa = (ca or {}).get("status")
        sb = (cb or {}).get("status")
        if _ok_status(sa) and _ok_status(sb):
            continue  # 两侧都对的格没有信息量
        by_field.setdefault(field, []).append((filename, entity_idx, ca or {}, cb or {}))

    counts = {f: len(v) for f, v in by_field.items()}
    order = [r["field"] for r in per_field if r["field"] in by_field]
    blocks: list[str] = []
    for field in order:
        rows = sorted(by_field[field], key=lambda r: (r[0], r[1]))
        star = '<span class="crit">★</span>' if next(
            (r["required"] for r in per_field if r["field"] == field), False
        ) else ""
        trs = []
        for filename, entity_idx, ca, cb in rows:
            truth = ca.get("truth") if ca.get("truth") is not None else cb.get("truth")
            ent = f' <span class="na">#{entity_idx + 1}</span>' if entity_idx else ""
            link = (
                f'<a class="doclink" href="{_e(base_url)}/p/{_e(quote(slug))}'
                f'?review={_e(quote(filename))}" target="_blank" rel="noopener">'
                f'{_e(filename)}</a>{ent}'
                if base_url else f"{_e(filename)}{ent}"
            )
            trs.append(
                f"<tr><td class=\"doc\">{link}</td>"
                f'<td class="val gt">{_e(_clip(truth))}</td>'
                f'<td class="num">{_badge(ca.get("status"))}</td>'
                f'<td class="val">{_e(_clip(ca.get("pred")))}</td>'
                f'<td class="num">{_badge(cb.get("status"))}</td>'
                f'<td class="val">{_e(_clip(cb.get("pred")))}</td></tr>'
            )
        # 每块自带表头 —— 展开某一块时别处的列说明是看不到的，靠页面顶部
        # 那一句解释「哪列是谁」等于让人记着往回翻。
        head = (
            f'<thead><tr><th style="width:20%">文档</th>'
            f'<th style="width:20%">GT（正确值）</th>'
            f'<th style="width:8%">{_e(a_name)}</th><th style="width:22%">它给了什么</th>'
            f'<th style="width:8%">{_e(b_name)}</th><th style="width:22%">它给了什么</th>'
            f"</tr></thead>"
        )
        blocks.append(
            f'<details class="drill" id="drill-{_e(field)}"><summary>'
            f'<span class="dfield">{_e(field)}</span>{star}'
            f'<span class="na">{len(rows)} 格有问题</span></summary>'
            f'<div class="wrap"><table>{head}<tbody>{"".join(trs)}</tbody></table></div>'
            f"</details>"
        )
    return counts, "".join(blocks)


def _badge(status: Optional[str]) -> str:
    zh = _STATUS_ZH.get(status or "", "—")
    cls = "b-ok" if _ok_status(status) else "b-bad"
    return f'<span class="kb {cls}">{_e(zh)}</span>'


def _build_html(
    *,
    slug: str,
    a_label: str,
    b_label: str,
    headline: str,
    verdict: str,
    overall: list[dict[str, Any]],
    per_field: list[dict[str, Any]],
    n_docs_graded: Optional[int],
    drill_counts: Optional[dict[str, int]] = None,
    drill_html: str = "",
) -> str:
    def cls(row: dict[str, Any]) -> str:
        a, b = row["a_acc"], row["b_acc"]
        if a is None or b is None:
            return "na"
        return "up" if b > a else ("down" if b < a else "")

    orows = []
    for r in overall:
        orows.append(
            f'<tr class="{ _e(r.get("css", "")) }"><td>{_e(r["label"])}</td>'
            f'<td class="num">{_e(r["a"])}</td><td class="num">{_e(r["b"])}</td>'
            f'<td class="num">{_e(r["delta"])}</td></tr>'
        )

    drill_counts = drill_counts or {}
    graded, faint = [], []
    for r in per_field:
        # 字段名有明细可看时做成锚点 —— 看到「-16.7pp」之后的下一个问题必然是
        # 「哪几篇」，让那一跳就在同一页里完成。没有问题格的字段不做链接
        # （点开是空的，反而误导）。
        n_drill = drill_counts.get(r["field"], 0)
        fname = (
            f'<a class="fjump" href="#drill-{_e(r["field"])}">{_e(r["field"])}</a>'
            f'<span class="na"> {n_drill}</span>'
            if n_drill else _e(r["field"])
        )
        cells = (
            f'<td>{fname}</td>'
            f'<td class="num">{_e(_pct(r["a_acc"]))}</td>'
            f'<td class="num">{_e(_pct(r["b_acc"]))}</td>'
            f'<td class="num { cls(r) }">{_e(_delta_str(r["a_acc"], r["b_acc"]))}</td>'
            f'<td class="num">{_e(r["b_hits"])}</td>'
            f'<td class="num">{_e(r["b_errs"])}</td>'
        )
        (faint if r["a_acc"] is None and r["b_acc"] is None else graded).append(
            f'<tr class="{ "hard" if r["required"] else "" }">{cells}</tr>'
        )

    faint_block = ""
    if faint:
        faint_block = (
            f'<details><summary>{len(faint)} 个字段 GT 从来没有值（不计入任何口径）'
            f'</summary><div class="wrap"><table><tbody>'
            + "".join(x.replace('<tr class="', '<tr class="faint ') for x in faint)
            + "</tbody></table></div></details>"
        )

    return f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(slug)} · 对比报告</title><style>{_CSS}</style></head><body>
<h1>{_e(b_label)} <span class="na">vs</span> {_e(a_label)}</h1>
<p class="sub">项目 {_e(slug)} · 对 ground truth 打分 · {_e(n_docs_graded or 0)} 篇</p>
<div class="verdict {_e(verdict)}">{_e(headline)}</div>

<h2>总体</h2>
<div class="wrap"><table>
<thead><tr><th>口径</th><th class="num">{_e(a_label)}</th><th class="num">{_e(b_label)}</th><th class="num">Δ</th></tr></thead>
<tbody>{''.join(orows)}</tbody></table></div>

<h2>逐字段</h2>
{('<div class="wrap"><table>'
  f'<thead><tr><th>字段</th><th class="num">{_e(a_label)}</th>'
  f'<th class="num">{_e(b_label)}</th>'
  '<th class="num">Δ</th><th class="num">对/有值格</th>'
  '<th class="num">错值·漏抽·多填</th></tr></thead>'
  f'<tbody>{"".join(graded)}</tbody></table></div>')
 if graded else
 '<p class="foot">没有可逐字段对比的数据 —— 这两次评测都没有「有值格」口径的结果。</p>'}
{faint_block}
<p class="foot">★ = schema 里标了 required 的重要字段。「有值格」= ground truth 该格有值的格子；
两边都空的格子不计入，因为那是送分题。字段名后的数字 = 至少一侧判错的格数，点它看逐格明细。</p>
{('<h2>逐格明细 —— 至少一侧判错的格</h2>'
  '<p class="foot">每个字段一栏，点开看是哪几篇、错成什么。文档名可点，'
  '打开该文档的复核页。</p>'
  + drill_html) if drill_html else ''}
</body></html>"""


def _build_no_gt_html(
    *, slug: str, a_label: str, b_label: str, headline: str, diff: dict[str, Any],
) -> str:
    """无 GT 态的白板：分歧清单，**零百分比**。

    红线：这一页上不许出现任何比率。「A 和 B 有多一致」不是准确率，而并排放两个
    百分数，读的人一定会把它当成准确率读走 —— 本项目栽过这个坑。所以这里只有
    计数（N 处分歧）和两侧的原值。"""
    by_field = "".join(
        f'<tr class="{ "hard" if r["required"] else "" }">'
        f'<td>{_e(r["field"])}</td><td class="num">{_e(r["n_diff"])}</td></tr>'
        for r in diff["by_field"]
    )

    rows = diff["cells"][:_MAX_DETAIL_ROWS]
    detail = "".join(
        f'<tr class="{ "hard" if c["required"] else "" }">'
        f'<td class="doc">{_e(c["filename"])}</td>'
        f'<td class="num">{_e(c["entity_idx"])}</td>'
        f'<td>{_e(c["field"])}</td>'
        f'<td class="val">{_e(c["a"]) if c["a"] is not None else "<span class=na>（空）</span>"}</td>'
        f'<td class="val">{_e(c["b"]) if c["b"] is not None else "<span class=na>（空）</span>"}</td>'
        f"</tr>"
        for c in rows
    )
    more = ""
    if len(diff["cells"]) > _MAX_DETAIL_ROWS:
        more = (
            f'<p class="foot">明细只显示前 {_MAX_DETAIL_ROWS} 行（共 '
            f'{len(diff["cells"])} 行）—— 回到 chat 里按字段要余下的。</p>'
        )

    mismatch = ""
    if diff["entity_count_mismatch"]:
        items = "".join(
            f'<li>{_e(m["filename"])} —— {_e(a_label)} {_e(m["n_a"])} 个实体，'
            f'{_e(b_label)} {_e(m["n_b"])} 个</li>'
            for m in diff["entity_count_mismatch"]
        )
        mismatch = (
            '<h2>⚠ 实体切分不一致</h2><p class="foot">这些文档两侧切出的实体数不同。'
            "只按重叠部分对齐会**系统性偏袒切得少的那一方**，裁决时要单独看。</p>"
            f"<ul>{items}</ul>"
        )

    return f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(slug)} · 分歧裁决</title><style>{_CSS}</style></head><body>
<h1>{_e(a_label)} <span class="na">vs</span> {_e(b_label)}</h1>
<p class="sub">项目 {_e(slug)} · 逐格比对两组预测（未对 ground truth 打分）</p>
<div class="verdict no_gt">{_e(headline)}</div>

<h2>按字段</h2>
<div class="wrap"><table>
<thead><tr><th>字段</th><th class="num">分歧</th></tr></thead>
<tbody>{by_field}</tbody></table></div>

<h2>明细</h2>
<div class="wrap"><table>
<thead><tr><th class="doc">文档</th><th class="num">实体</th><th>字段</th>
<th class="val">{_e(a_label)}</th><th class="val">{_e(b_label)}</th></tr></thead>
<tbody>{detail}</tbody></table></div>
{more}
{mismatch}
<p class="foot">★ = schema 里标了 required 的重要字段，先裁这些。
定夺一格就等于造了一格 ground truth —— 裁完回 chat 说一声，就能出真正的对比报告。
这一页没有准确率，也不会有：两个模型互相有多一致，不是准确率。</p>
</body></html>"""


def _source_label(workspace: Path, slug: str, source: str) -> str:
    """prediction source 的人读名字：实验读它 meta 里的 label（那是「模型 ·
    prompt」拼出来的），`_draft` 就是当前活动配置。

    报告态的 `_side_label` 是同一条原则 —— `ex_6046df1xwwaa` 对产品经理毫无
    意义，repo 惯例是 chat 里说模型名，id 只留给 plan 与运维脚本。"""
    if source == "_draft":
        return "当前配置（草稿）"
    from app.workspace.paths import experiment_meta_path
    try:
        meta = json.loads(
            experiment_meta_path(workspace, slug, source).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return source
    label = meta.get("label")
    return str(label) if label else source


async def _render_no_gt(
    workspace: Path, slug: str, a: str, b: str,
) -> dict[str, Any]:
    """`a`/`b` 是 prediction source（`_draft` / `ex_…`）时走这条：没有 GT，
    产出的是待裁决队列，不是报告。"""
    from app.tools.diff_predictions import DiffSourceError, diff_predictions

    try:
        diff = await diff_predictions(workspace, slug, a, b)
    except DiffSourceError as e:
        raise CompareError(e.error_code, e.error_message_en) from e

    a_label = _source_label(workspace, slug, a)
    b_label = _source_label(workspace, slug, b)
    n_req = diff["n_diff_required"]
    headline = (
        f"{diff['n_diff']} 处分歧待裁决"
        + (f"（其中重要字段 {n_req} 处，先裁这些）" if n_req else "")
        + f" · 共对齐 {diff['n_cells']} 格"
    )
    if diff["n_diff"] == 0:
        headline = (
            f"两侧在 {diff['n_cells']} 格上完全一致 —— 没有分歧可裁。"
            "一致不等于都对：要判准确率，得先 review 出 ground truth。"
        )

    return {
        "headline": headline,
        "verdict": "no_gt",
        "a_label": a_label,
        "b_label": b_label,
        # 报告态的两张表在这里是空的 —— 没有 GT 就没有任何比率可填。
        "overall": [],
        "per_field": [],
        "n_diff": diff["n_diff"],
        "n_diff_required": n_req,
        "html": _build_no_gt_html(
            slug=slug, a_label=a_label, b_label=b_label,
            headline=headline, diff=diff,
        ),
    }


async def render_compare_board(
    workspace: Path, slug: str, a: str, b: str,
) -> dict[str, Any]:
    """读两次 eval 的 summary，产一份自含 HTML 的对比报告。

    `a` = 在位（baseline）的 eval ts，`b` = 挑战者的 eval ts —— 与
    `/projects/<slug>/eval/compare?a=&b=` 的既有约定同向，别调换。

    返回 `{headline, verdict, a_label, b_label, overall, per_field, html}`；
    `html` 只走 HTTP 孪生进 iframe，不进 tool 的 text 返回。

    `a`/`b` 也可以是 prediction source（`_draft` / `ex_…`）—— 那表示这个项目还
    没有 ground truth，白板转成**分歧裁决清单**（零百分比）。两种形态靠形状区分，
    见 `is_eval_ts`。"""
    if not is_eval_ts(a) and not is_eval_ts(b):
        return await _render_no_gt(workspace, slug, a, b)
    if is_eval_ts(a) != is_eval_ts(b):
        raise CompareError(
            "compare_mixed_handles",
            f"a={a!r} and b={b!r} are different kinds of handle — pass two eval "
            f"timestamps (with ground truth) or two prediction sources (without)",
        )

    sa = _load_summary(workspace, slug, a)
    sb = _load_summary(workspace, slug, b)

    a_label, b_label = _side_label(sa, a), _side_label(sb, b)
    # 同一模型 × 同一 prompt 的两次跑批标签会撞在一起（「X vs X」读不出谁是谁）。
    # 撞了才补 ts —— 没撞时 ts 是噪音，产品经理读的是模型名。
    if a_label == b_label:
        a_label, b_label = f"{a_label}（{a}）", f"{b_label}（{b}）"
    verdict, delta_cells, delta_pp = _verdict(sa, sb)

    _, a_den = _totals(sa)
    _, b_den = _totals(sb)

    # headline：结论一句话。措辞受 skill 的判据一节约束 —— noise 时不许出现
    # 「略优 / 倾向」这类把噪声包装成结论的词。
    if delta_pp is None:
        # 两种 None 长得一样，给的建议却完全相反 —— 生产 smoke 上撞到过：一个
        # 有 638 格 GT 的项目被告知「先做 review」，因为它比的是 M12 时代打的分。
        #   · 打过分但 blob 是旧版（`n_reviewed > 0`）→ 重跑一次就有硬指标
        #   · 真的没有 GT（`n_reviewed == 0`）→ 才是「先去 review」
        graded = max(sa.n_reviewed or 0, sb.n_reviewed or 0)
        verdict = "stale" if graded > 0 else "no_gt"
        if graded > 0:
            headline = (
                f"这两次 eval 是旧版本打的分，没有「有值格」口径的数据"
                f"（{graded} 篇已打分）—— 重新跑一次评测就有硬指标了。"
                f"下面只有官方 macro 可读，而它把两边都空的格子算作预测正确。"
            )
        else:
            headline = "还没有 ground truth —— 先给一些文档做 review，才谈得上准确率。"
    elif verdict == "win":
        headline = (
            f"{b_label} 在有值格上 {delta_pp:+.1f}pp（多对 {delta_cells} 格 / 共 {b_den} 格），"
            f"两条判据都跨过了 —— 建议换。"
        )
    elif verdict == "lose":
        headline = (
            f"{b_label} 在有值格上 {delta_pp:+.1f}pp（少对 {abs(delta_cells)} 格 / 共 {b_den} 格），"
            f"明显更差 —— 不要换，维持 {a_label}。"
        )
    else:
        headline = (
            f"差距 {delta_pp:+.1f}pp（{delta_cells:+d} 格 / 共 {b_den} 格），"
            f"没有同时跨过「多对 >{_MIN_DELTA_CELLS} 格」与「>{_MIN_DELTA_PP:.0f}pp」两条线 —— "
            f"分不出高下，维持现状。"
        )

    overall: list[dict[str, Any]] = []
    # ★重要字段那一行：没人标 required 就整行省略，绝不报 0%。
    if (sa.n_required_fields or 0) > 0 or (sb.n_required_fields or 0) > 0:
        overall.append({
            "label": "★重要字段 · 有值格",
            "a": _pct(sa.required_cell_accuracy_nonempty),
            "b": _pct(sb.required_cell_accuracy_nonempty),
            "delta": _delta_str(sa.required_cell_accuracy_nonempty,
                                sb.required_cell_accuracy_nonempty),
            "css": "hard",  # ★ 只属于这一行
        })
    overall.append({
        "label": "全字段 · 有值格",
        "a": _pct(sa.cell_accuracy_nonempty),
        "b": _pct(sb.cell_accuracy_nonempty),
        "delta": _delta_str(sa.cell_accuracy_nonempty, sb.cell_accuracy_nonempty),
        "css": "key",  # 头条加粗，但它不是「重要字段」那一档，不能带 ★
    })
    overall.append({
        "label": "整篇零错文档",
        "a": f"{sa.n_docs_perfect or 0}/{sa.n_docs_graded or 0}",
        "b": f"{sb.n_docs_perfect or 0}/{sb.n_docs_graded or 0}",
        "delta": f"{(sb.n_docs_perfect or 0) - (sa.n_docs_perfect or 0):+d}",
        "css": "",
    })
    overall.append({
        "label": "官方 macro（含两边都空的送分格）",
        "a": _pct(sa.field_accuracy_macro),
        "b": _pct(sb.field_accuracy_macro),
        "delta": _delta_str(sa.field_accuracy_macro, sb.field_accuracy_macro),
        "css": "faint",
    })

    # 两侧分母不同 = 某一侧在部分文档/实体上没有产出预测（实体切分失败是常见
    # 原因）。静默按重叠打分会系统性偏袒缺失的那一方，所以显式说出来。
    if a_den != b_den:
        overall.append({
            "label": "⚠ 两侧有值格分母不同（某侧缺预测）",
            "a": str(a_den), "b": str(b_den),
            "delta": f"{b_den - a_den:+d}", "css": "faint",
        })

    # 逐格明细：汇总回答不了「哪几篇、错成什么」，而那是看到一行 Δ 之后必然
    # 要问的下一个问题。历史 blob 没有 cells.jsonl —— 那时明细区整个消失，
    # 汇总照常（`_load_cells` 返回空）。
    a_cells = _load_cells(workspace, slug, a)
    b_cells = _load_cells(workspace, slug, b)

    a_by_field = {f.field: f for f in sa.per_field}
    per_field: list[dict[str, Any]] = []
    for fb in sb.per_field:
        fa = a_by_field.get(fb.field)
        b_num, b_den_f = _nonempty_counts(fb)
        per_field.append({
            "field": fb.field,
            "required": fb.required,
            "a_acc": fa.accuracy_nonempty if fa else None,
            "b_acc": fb.accuracy_nonempty,
            "b_hits": f"{b_num}/{b_den_f}",
            "b_errs": f"{fb.n_wrong}·{fb.n_missing}·{fb.n_spurious}",
        })
    per_field.sort(key=_delta_sort_key, reverse=True)

    from app.config import get_settings as _gs
    base_url = _gs().public_base_url.rstrip("/")
    drill_counts, drill_html = _build_drilldowns(
        a_cells, b_cells, per_field, slug=slug, base_url=base_url,
        a_label=a_label, b_label=b_label,
    )

    return {
        "headline": headline,
        "verdict": verdict,
        "a_label": a_label,
        "b_label": b_label,
        "delta_cells": delta_cells,
        "delta_pp": delta_pp,
        "overall": overall,
        "per_field": per_field,
        "html": _build_html(
            slug=slug, a_label=a_label, b_label=b_label,
            headline=headline, verdict=verdict, overall=overall,
            per_field=per_field,
            # legacy blob 没有 n_docs_graded —— 回退到 n_reviewed，否则副标题
            # 写「0 篇」而 headline 写「19 篇已打分」，同一张纸上自相矛盾。
            n_docs_graded=sb.n_docs_graded or sb.n_reviewed,
            drill_counts=drill_counts, drill_html=drill_html,
        ),
    }
