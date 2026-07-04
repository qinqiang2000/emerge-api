"""render_review_board (A 方案, 2026-07-04) — 审单核对白板渲染核心 + HTTP 孪生。

结构化/文本审单文档的「原件 + 圈注」白板：两张原始表格横排，数量核对不过的商品组
红框行 + 同号徽章。渲染 0 LLM，纯计算——测试直接在 tmp workspace 造 docs/*.json +
predictions/_draft/*.json（无 provider、无 OCR、无 SDK），断言 verdict/tally/高亮行命中/
HTML 转义/无预测跳过。路由测试经 TestClient 打 HTTP 孪生（env_isolation 把
EMERGE_WORKSPACE_ROOT 指向 per-test 根，open mode → bind_workspace 解析到扁平根）。
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.review_board_render import render_review_board
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import docs_dir, prediction_draft_path


# --- helpers -----------------------------------------------------------------


def _write_doc(workspace: Path, slug: str, doc_id: str, doc: dict) -> str:
    """一份审单文档 docs/审核数据_{id}.json，返回文件名。"""
    fn = f"审核数据_{doc_id}.json"
    docs_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    atomic_write_json(docs_dir(workspace, slug) / fn, doc)
    return fn


def _write_pred(workspace: Path, slug: str, filename: str, entity: dict,
                model_label: str = "deepseek-v4-flash") -> None:
    atomic_write_json(
        prediction_draft_path(workspace, slug, filename),
        {"entities": [entity], "_run": {"model_label": model_label}},
    )


def _fail_doc(doc_id: str = "2994530") -> dict:
    """一份「数量不符」文档：维生素B1片发票280瓶 / 结算14盒，问题组含两侧细单ID。"""
    return {
        "结算总单ID": doc_id,
        "发票主信息": {
            "供应商名称(SUPPLYNAME)": "安徽晶瑞药业有限公司",
            "含税总金额(TOTAL_IN)": "14107.50",
            "金税发票号码(GOLDTAXINVOICENUM)": "26342000001493707741",
            "总单备注(MEMO)": "发票云生成",
        },
        "采购发票明细行": [
            {"发票货物或应税劳务名称": "*化学药品制剂*布洛芬缓释胶囊", "发票规格型号": "0.3g*12粒/板*2板/盒",
             "发票商品单位": "盒", "发票商品数量": 60.0, "发票含税单价": 5.6, "发票含税金额": 336.0,
             "发票税率": 0.13, "采购发票细单ID": 42041920},
            {"发票货物或应税劳务名称": "*化学药品制剂*维生素B1片", "发票规格型号": "10mg*100片/瓶",
             "发票商品单位": "瓶", "发票商品数量": 280.0, "发票含税单价": 2.75, "发票含税金额": 770.0,
             "发票税率": 0.13, "采购发票细单ID": 42041923},
        ],
        "结算明细行": [
            {"商品名称(GOODSNAME)": "回春散", "规格(GOODSTYPE)": "0.3g*6袋", "单位(GOODSUNIT)": "盒",
             "数量(GOODSQTY)": "100.000000", "单价(UNITPRICE)": "61.2", "行金额(含税)(TOTAL_LINE)": "6120.00",
             "行类别(ZX_LINETYPENAME)": "入库单", "备注(MEMO)": "", "结算细单ID(SUSETDTLID)": "49523615"},
            {"商品名称(GOODSNAME)": "维生素B1片", "规格(GOODSTYPE)": "10mg*100`s", "单位(GOODSUNIT)": "盒",
             "数量(GOODSQTY)": "14.000000", "单价(UNITPRICE)": "55", "行金额(含税)(TOTAL_LINE)": "770.00",
             "行类别(ZX_LINETYPENAME)": "入库单", "备注(MEMO)": "", "结算细单ID(SUSETDTLID)": "49522378"},
        ],
        "程序预计算": {
            "商品组配对明细(同一商品的结算多行已合并求和)": [
                {"商品": "布洛芬缓释胶囊",
                 "发票侧": {"数量合计": 60, "细单ID": [42041920]},
                 "结算侧": {"数量合计": 60, "细单ID": ["49523614"]},
                 "金额一致": True, "数量合计一致": True},
                {"商品": "维生素B1片",
                 "发票侧": {"数量合计": 280, "单位": "瓶", "细单ID": [42041923]},
                 "结算侧": {"数量合计": 14, "单位": "盒", "细单ID": ["49522378"]},
                 "金额一致": True, "数量合计一致": False, "数量比(发票合计/结算合计)": 20},
            ],
        },
    }


def _pass_doc(doc_id: str = "2981974") -> dict:
    """一份「各组数量合计一致」文档：无问题组。"""
    return {
        "结算总单ID": doc_id,
        "发票主信息": {"供应商名称(SUPPLYNAME)": "国药控股", "含税总金额(TOTAL_IN)": "2005.50"},
        "采购发票明细行": [
            {"发票货物或应税劳务名称": "阿瑞匹坦胶囊", "发票商品单位": "盒", "发票商品数量": 5.0,
             "发票含税金额": 2005.5, "采购发票细单ID": 41692959},
        ],
        "结算明细行": [
            {"商品名称(GOODSNAME)": "阿瑞匹坦胶囊", "单位(GOODSUNIT)": "盒", "数量(GOODSQTY)": "5.000000",
             "行金额(含税)(TOTAL_LINE)": "2005.50", "结算细单ID(SUSETDTLID)": "48103903"},
        ],
        "程序预计算": {
            "商品组配对明细(同一商品的结算多行已合并求和)": [
                {"商品": "阿瑞匹坦胶囊",
                 "发票侧": {"数量合计": 5, "细单ID": [41692959]},
                 "结算侧": {"数量合计": 5, "细单ID": ["48103903"]},
                 "金额一致": True, "数量合计一致": True},
            ],
        },
    }


# --- renderer tests ----------------------------------------------------------


async def test_verdict_and_tally(workspace: Path) -> None:
    slug = "审单dogfood"
    fn_f = _write_doc(workspace, slug, "2994530", _fail_doc())
    fn_p = _write_doc(workspace, slug, "2981974", _pass_doc())
    _write_pred(workspace, slug, fn_f, {"pass": False, "reason": "维生素B1片数量不符", "issues": []})
    _write_pred(workspace, slug, fn_p, {"pass": True, "reason": "各商品组数量合计一致", "issues": []})

    out = await render_review_board(workspace, slug)

    assert out["tally"] == {"pass": 1, "fail": 1, "unclear": 0}
    assert out["model_label"] == "deepseek-v4-flash"
    by_id = {d["id"]: d for d in out["docs"]}
    assert by_id["2994530"]["verdict"] == "fail"
    assert by_id["2994530"]["reason"] == "维生素B1片数量不符"
    assert by_id["2994530"]["supplier"] == "安徽晶瑞药业有限公司"
    assert by_id["2981974"]["verdict"] == "pass"


async def test_problem_group_rows_highlighted(workspace: Path) -> None:
    """问题组（维生素B1片）的两侧细单ID → 两表各一行标 hit + 徽章①；pass 单无高亮。"""
    slug = "审单dogfood"
    fn = _write_doc(workspace, slug, "2994530", _fail_doc())
    _write_pred(workspace, slug, fn, {"pass": False, "reason": "数量不符", "issues": []})

    out = await render_review_board(workspace, slug)
    html = out["html_by_id"]["2994530"]
    body = html.split("</style>")[1]  # 排除 CSS 里的 .hit/.qty-hit 定义

    # 发票侧维生素B1片行 + 结算侧维生素B1片行 = 2 个 hit 行
    assert body.count('class="hit"') == 2
    # 同号徽章①出现在两表各一次
    assert body.count('class="badge">1<') == 2
    # 数量单元格标红（发票 280 + 结算 14）
    assert body.count("qty-hit") == 2
    # 布洛芬（数量合计一致）不高亮——其细单ID 42041920 不在任何 hit 行首
    assert "布洛芬缓释胶囊" in body


async def test_pass_doc_no_highlight(workspace: Path) -> None:
    slug = "审单dogfood"
    fn = _write_doc(workspace, slug, "2981974", _pass_doc())
    _write_pred(workspace, slug, fn, {"pass": True, "reason": "各商品组数量合计一致", "issues": []})

    out = await render_review_board(workspace, slug)
    html = out["html_by_id"]["2981974"]
    body = html.split("</style>")[1]  # 排除 CSS 定义
    assert 'class="hit"' not in body
    assert "qty-hit" not in body
    assert "stamp pass" in html
    assert "阿瑞匹坦胶囊" in html
    # 通过单无问题行 → 不注入「只看问题行」开关
    assert "hitonly" not in body


async def test_hit_only_toggle_on_fail_doc(workspace: Path) -> None:
    """驳回单注入「只看问题行」纯 CSS 开关(checkbox 前置于 .tables);计数=红框行数。"""
    slug = "审单dogfood"
    fn = _write_doc(workspace, slug, "2994530", _fail_doc())
    _write_pred(workspace, slug, fn, {"pass": False, "reason": "数量不符", "issues": []})

    html = (await render_review_board(workspace, slug))["html_by_id"]["2994530"]
    body = html.split("</style>")[1]
    assert 'id="hitonly"' in body
    assert "只看问题行（2）" in body  # 发票侧1 + 结算侧1 = 2 红框行
    # checkbox 必须前置于 .tables，:checked ~ .tables 选择器才生效
    assert body.index('id="hitonly"') < body.index('class="tables"')
    # 隐藏非问题行的规则在 CSS 里
    assert ".hitonly:checked ~ .tables tbody tr:not(.hit)" in html


async def test_two_tables_horizontal_and_structure(workspace: Path) -> None:
    slug = "审单dogfood"
    fn = _write_doc(workspace, slug, "2994530", _fail_doc())
    _write_pred(workspace, slug, fn, {"pass": False, "reason": "数量不符", "issues": []})

    html = (await render_review_board(workspace, slug))["html_by_id"]["2994530"]
    assert '<div class="tables">' in html      # flex 横排容器
    assert html.count("<table>") == 2           # 采购发票明细 + 结算细单
    assert "采购发票明细" in html and "结算细单" in html
    assert "stamp fail" in html and "reason fail" in html
    assert "prefers-color-scheme" in html       # 明暗双主题


async def test_html_escapes_untrusted_doc_content(workspace: Path) -> None:
    """文档内容是不可信数据 → 注入的 <script> 必须被转义，不能落成活标签。"""
    slug = "审单dogfood"
    doc = _pass_doc("9999")
    doc["结算明细行"][0]["商品名称(GOODSNAME)"] = "<script>alert(1)</script>"
    fn = _write_doc(workspace, slug, "9999", doc)
    _write_pred(workspace, slug, fn, {"pass": True, "reason": "ok", "issues": []})

    html = (await render_review_board(workspace, slug))["html_by_id"]["9999"]
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


async def test_doc_without_prediction_skipped(workspace: Path) -> None:
    slug = "审单dogfood"
    _write_doc(workspace, slug, "2994530", _fail_doc())   # 有 doc 无预测
    fn_p = _write_doc(workspace, slug, "2981974", _pass_doc())
    _write_pred(workspace, slug, fn_p, {"pass": True, "reason": "ok", "issues": []})

    out = await render_review_board(workspace, slug)
    ids = {d["id"] for d in out["docs"]}
    assert ids == {"2981974"}                    # 无预测的 2994530 被跳过
    assert "2994530" not in out["html_by_id"]


async def test_empty_project(workspace: Path) -> None:
    out = await render_review_board(workspace, "空项目")
    assert out["docs"] == []
    assert out["html_by_id"] == {}
    assert out["tally"] == {"pass": 0, "fail": 0, "unclear": 0}


# --- HTTP twin ---------------------------------------------------------------


def test_http_twin_matches_tool(workspace: Path) -> None:
    slug = "审单dogfood"
    fn = _write_doc(workspace, slug, "2994530", _fail_doc())
    _write_pred(workspace, slug, fn, {"pass": False, "reason": "数量不符", "issues": []})

    client = TestClient(app)
    r = client.get(f"/lab/projects/{slug}/review/board-render")
    assert r.status_code == 200
    body = r.json()
    assert body["tally"] == {"pass": 0, "fail": 1, "unclear": 0}
    assert body["docs"][0]["id"] == "2994530"
    assert "2994530" in body["html_by_id"]
