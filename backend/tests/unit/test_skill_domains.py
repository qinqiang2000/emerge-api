"""Progressive disclosure (2026-06-10) — slim always-on core + on-demand
domain playbooks. These lock the size budget (the whole point of the split)
and the content-preservation invariants."""
from __future__ import annotations

import pytest

from app.skills import SKILL_DOMAINS, load_domain_skill, load_skill

CORE_LINE_BUDGET = 350


def test_core_skill_stays_slim() -> None:
    """The core is always-on context tax on EVERY turn. If this fails, move
    the new content into a domain file instead of growing the core."""
    core = load_skill("emerge_extractor")
    n = len(core.splitlines())
    assert n <= CORE_LINE_BUDGET, (
        f"emerge_extractor.md is {n} lines (> {CORE_LINE_BUDGET}) — "
        "move domain detail into app/skills/domains/*.md"
    )


def test_every_domain_loads_and_is_substantial() -> None:
    for d in SKILL_DOMAINS:
        text = load_domain_skill(d)
        assert len(text.splitlines()) > 20, f"domain {d} suspiciously small"


def test_unknown_domain_rejected() -> None:
    for bad in ("nope", "../emerge_extractor", "audit/../../.env", ""):
        with pytest.raises(KeyError):
            load_domain_skill(bad)


def test_core_routes_to_every_domain() -> None:
    """The router table must mention each domain — a domain nobody routes to
    is dead context."""
    core = load_skill("emerge_extractor")
    for d in SKILL_DOMAINS:
        assert f'read_skill("{d}")' in core, f"core never routes to {d}"


def test_moved_contracts_live_in_domains_not_core() -> None:
    """Spot-check the heaviest moved sections: present in their domain file,
    absent from the core (no double-pay)."""
    core = load_skill("emerge_extractor")
    assert "corrections_since_tune" in load_domain_skill("review")
    assert "corrections_since_tune" not in core
    assert "save_reviewed_audit" in load_domain_skill("match_audit")
    assert "组不变" in load_domain_skill("match_audit")
    assert "summary_ts" in load_domain_skill("experiments")
    assert "import_schema_from_yaml" in load_domain_skill("attachments")
    assert "agent_brain" in load_domain_skill("self")


def test_red_lines_stay_in_core() -> None:
    """Red lines must never move out of the always-on core."""
    core = load_skill("emerge_extractor")
    for marker in ("write_schema", "image few-shot", "bbox",
                   "run_audit", "freeze_version", "_published/"):
        assert marker in core, f"red-line marker {marker!r} missing from core"


# ── compare 口径护栏（2026-08-20 compare-for-pm plan §2 T1）────────────────
# 这条 flow 是给「不懂代码的产品经理」读的结论负责的，判据一旦被稀释成「建议
# 谨慎」，单轮跑批噪声就会被当成结论。锁住措辞而不只是锁住存在性。

def _compare_flow_section() -> str:
    """`## Compare flow` 到下一个 `## ` 之间的正文。逐字段口径只在这一节生效——
    `## Eval` 那节仍报 doc_accuracy（单侧打分的既有契约，本 plan 不动它）。"""
    text = load_domain_skill("experiments")
    start = text.index("## Compare flow")
    rest = text[start + len("## Compare flow"):]
    nxt = rest.find("\n## ")
    return rest if nxt < 0 else rest[:nxt]


def test_compare_flow_headlines_the_hard_metrics() -> None:
    sec = _compare_flow_section()
    for key in ("cell_accuracy_nonempty", "required_cell_accuracy_nonempty",
                "n_docs_perfect", "n_required_fields"):
        assert key in sec, f"compare flow never mentions {key!r}"


def test_compare_flow_does_not_report_doc_accuracy() -> None:
    """`doc_accuracy` 会出现「0 篇全对却 84.4%」的自相矛盾读数——compare 结论里
    用「整篇零错 n/N」代替。允许出现在「不要报」的禁令句里，但不能作为要报的
    指标 key 出现在口径表中。"""
    sec = _compare_flow_section()
    table_rows = [ln for ln in sec.splitlines()
                  if ln.strip().startswith("|") and "`doc_accuracy`" in ln]
    assert not table_rows, f"doc_accuracy still listed as a reportable metric: {table_rows}"
    assert "不要报 `doc_accuracy`" in sec, "the explicit ban on doc_accuracy went missing"


def test_compare_flow_gates_the_verdict_on_noise() -> None:
    """双条件判据 + 「不许下结论」的措辞。这是本 plan 最贵的一条规则。"""
    sec = _compare_flow_section()
    assert "Δ格数" in sec and "Δpp" in sec, "the two-condition verdict gate is gone"
    assert "分不出高下" in sec, "the noise-band verdict wording is gone"
    assert "不许" in sec, "the gate got softened from 不许 to a suggestion"


def test_compare_flow_never_reports_na_as_zero() -> None:
    sec = _compare_flow_section()
    assert "绝不报成 0%" in sec


def test_compare_flow_has_both_rendering_branches() -> None:
    """interface-aware 渲染是人格红线：browser + headless 两个分支都要写。"""
    sec = _compare_flow_section()
    assert "**browser**" in sec and "**headless**" in sec


def test_experiments_domain_carries_the_judgment_pitfalls() -> None:
    """HANDOFF 的方法论搬家到 skill——方法论进 agent 上下文，数字进报告。"""
    text = load_domain_skill("experiments")
    assert "判断陷阱" in text
    assert "一致率" in text, "the 'agreement rate is not accuracy' trap is missing"
    assert "自洽性是证伪工具" in text


def test_compare_flow_delegates_the_numbers_to_the_board() -> None:
    """口径只能有一个实现。skill 自己再算一遍 = chat 和报告会给出两个数字。"""
    sec = _compare_flow_section()
    assert "render_board(kind='compare'" in sec
    assert "Do not hand-roll the numbers" in sec


def test_empty_reviewed_no_longer_dead_ends() -> None:
    """没有 GT 不是死路——产品经理接手的新项目 100% 是这个状态。"""
    sec = _compare_flow_section()
    assert "do NOT refuse and do NOT stop" in sec


def test_no_gt_branch_bans_percentages() -> None:
    """一致率不是准确率。无 GT 的输出里出现任何百分比,读的人都会当成准确率。"""
    text = load_domain_skill("experiments")
    start = text.index("### 没有 GT")
    sec = text[start:text.index("### 判断陷阱")]
    assert "不许出现百分比" in sec
    assert "diff_predictions" in sec
    assert "entity_count_mismatch" in sec, "the entity-split trap is unguarded"
    assert "required" in sec, "important fields must be adjudicated first"


def test_no_gt_branch_points_at_the_board() -> None:
    """dogfood 抓到的：白板的裁决态做好了，skill 却没告诉 agent 用 —— 于是它把
    86 处分歧全铺进了对话。功能存在 ≠ agent 知道它存在。"""
    text = load_domain_skill("experiments")
    sec = text[text.index("### 没有 GT"):text.index("### 判断陷阱")]
    assert "render_board(kind='compare'" in sec
    assert "**browser**" in sec and "**headless**" in sec
    assert "不要**把几十行明细铺进对话" in sec
    # dogfood 二轮：agent 拿到 diff_predictions 的全量数据后，把「再调一次
    # render_board 取链接」当成重复劳动而跳过。链接只是字符串拼接 —— 给模板，
    # 别要求它多跑一趟工具。
    assert "?compareboard=1&a=" in sec
    assert "不必为了拿链接再调一次工具" in sec
    # 同一轮：找两个实验花了 3×Bash + 7×Read。投影工具就在那里没人指路。
    assert "list_experiments" in sec
