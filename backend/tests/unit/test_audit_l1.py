"""L1 audit fast path (app/match/audit_l1.py — A3).

Deterministic eq/range checks over extracted fields; every unresolvable spec
returns None (→ the rule silently goes to the judge — never an error, never an
"extract first" demand).
"""
from __future__ import annotations

from app.match.audit_l1 import try_l1
from app.schemas.match import AuditRule, L1Check, L1FieldRef


def _rule(check: dict, *, level: str = "critical", text: str = "规则") -> AuditRule:
    return AuditRule(rule=text, level=level, check=L1Check(**check))


_REF = lambda doc, field: {"doc": doc, "field": field}


# --- eq: numbers --------------------------------------------------------------


def test_eq_number_thousands_and_currency_within_tol():
    rule = _rule({
        "type": "eq",
        "left": _REF("报价单", "total"),
        "right": _REF("收货单", "amount"),
        "tol": 0.01,
    })
    fields = {
        "报价单.pdf": {"total": "¥370,815.56"},
        "收货单.jpg": {"amount": "370815.56"},
    }
    rc = try_l1(rule, fields)
    assert rc is not None
    assert rc.status == "pass"
    assert rc.decided_by == "l1"
    assert rc.level == "critical"
    assert rc.reason.startswith("L1:")
    assert "370815.56" in rc.reason or "370,815.56" in rc.reason


def test_eq_number_outside_tol_fails():
    rule = _rule({
        "type": "eq",
        "left": _REF("报价单", "total"),
        "right": _REF("收货单", "amount"),
        "tol": 0.01,
    })
    fields = {"报价单.pdf": {"total": "100.00"}, "收货单.jpg": {"amount": "100.50"}}
    rc = try_l1(rule, fields)
    assert rc is not None and rc.status == "fail"
    assert "!=" in rc.reason


def test_eq_number_against_constant():
    rule = _rule({"type": "eq", "left": _REF("报价单", "total"), "right": 1200})
    fields = {"报价单.pdf": {"total": "1,200.00"}}
    rc = try_l1(rule, fields)
    assert rc is not None and rc.status == "pass"


# --- eq: strings (unicode canonical) ------------------------------------------


def test_eq_string_canonical_fullwidth_equivalence():
    # NFKC folds full-width parens — the canonical forms agree.
    rule = _rule({
        "type": "eq",
        "left": _REF("报价单", "brand_client"),
        "right": "环胜电子商务（上海）有限公司",
    })
    fields = {"报价单.pdf": {"brand_client": "环胜电子商务(上海)有限公司"}}
    rc = try_l1(rule, fields)
    assert rc is not None and rc.status == "pass"


def test_eq_string_mismatch_fails():
    rule = _rule({
        "type": "eq", "left": _REF("报价单", "brand_client"), "right": "环胜",
    })
    fields = {"报价单.pdf": {"brand_client": "别家公司"}}
    rc = try_l1(rule, fields)
    assert rc is not None and rc.status == "fail"


# --- eq: dates ----------------------------------------------------------------


def test_eq_date_different_formats():
    rule = _rule({
        "type": "eq",
        "left": _REF("订单", "complete_date"),
        "right": _REF("报价单", "end_date"),
    })
    fields = {
        "订单.pdf": {"complete_date": "2025-02-28"},
        "报价单.pdf": {"end_date": "2025/02/28"},
    }
    rc = try_l1(rule, fields)
    assert rc is not None and rc.status == "pass"


# --- range ---------------------------------------------------------------------


def test_range_date_inside_period():
    rule = _rule({
        "type": "range",
        "value": _REF("订单", "complete_date"),
        "low": _REF("报价单", "period_start"),
        "high": _REF("报价单", "period_end"),
    })
    fields = {
        "订单.pdf": {"complete_date": "2025-02-28"},
        "报价单.pdf": {"period_start": "2025-01-15", "period_end": "2025-02-28"},
    }
    rc = try_l1(rule, fields)
    assert rc is not None and rc.status == "pass"
    assert "∈" in rc.reason


def test_range_date_outside_period_fails():
    rule = _rule({
        "type": "range",
        "value": _REF("订单", "complete_date"),
        "low": "2025-01-15",
        "high": "2025-02-28",
    })
    fields = {"订单.pdf": {"complete_date": "2025-03-01"}}
    rc = try_l1(rule, fields)
    assert rc is not None and rc.status == "fail"
    assert "∉" in rc.reason


def test_range_numeric():
    rule = _rule({
        "type": "range", "value": _REF("报价单", "total"), "low": 0, "high": 500000,
    })
    fields = {"报价单.pdf": {"total": "¥370,815.56"}}
    rc = try_l1(rule, fields)
    assert rc is not None and rc.status == "pass"


def test_range_unparsable_defers_to_judge():
    # value parses as neither number nor date → None (judge decides)
    rule = _rule({
        "type": "range", "value": _REF("报价单", "total"), "low": 0, "high": 100,
    })
    fields = {"报价单.pdf": {"total": "面议"}}
    assert try_l1(rule, fields) is None


# --- doc resolution -------------------------------------------------------------


def test_doc_unique_substring_match():
    rule = _rule({"type": "eq", "left": _REF("报价单", "total"), "right": "100"})
    fields = {"2026年Q1报价单-final.pdf": {"total": "100"}, "收货单.jpg": {"total": "1"}}
    rc = try_l1(rule, fields)
    assert rc is not None and rc.status == "pass"


def test_doc_ambiguous_substring_defers_to_judge():
    rule = _rule({"type": "eq", "left": _REF("报价单", "total"), "right": "100"})
    fields = {"报价单A.pdf": {"total": "100"}, "报价单B.pdf": {"total": "100"}}
    assert try_l1(rule, fields) is None


def test_doc_exact_match_wins_over_substring_ambiguity():
    rule = _rule({"type": "eq", "left": _REF("报价单.pdf", "total"), "right": "100"})
    fields = {"报价单.pdf": {"total": "100"}, "报价单.pdf.bak": {"total": "999"}}
    rc = try_l1(rule, fields)
    assert rc is not None and rc.status == "pass"


def test_doc_no_hit_defers_to_judge():
    rule = _rule({"type": "eq", "left": _REF("发票", "total"), "right": "100"})
    fields = {"报价单.pdf": {"total": "100"}}
    assert try_l1(rule, fields) is None


# --- field absence / no spec -----------------------------------------------------


def test_field_missing_defers_to_judge():
    rule = _rule({"type": "eq", "left": _REF("报价单", "total"), "right": "100"})
    assert try_l1(rule, {"报价单.pdf": {"other": "1"}}) is None


def test_field_empty_string_defers_to_judge():
    rule = _rule({"type": "eq", "left": _REF("报价单", "total"), "right": "100"})
    assert try_l1(rule, {"报价单.pdf": {"total": "  "}}) is None


def test_no_check_spec_defers_to_judge():
    assert try_l1(AuditRule(rule="乙方盖红章"), {"报价单.pdf": {"a": 1}}) is None


def test_warning_level_carried_through():
    rule = _rule(
        {"type": "eq", "left": _REF("报价单", "total"), "right": "999"},
        level="warning",
    )
    rc = try_l1(rule, {"报价单.pdf": {"total": "100"}})
    assert rc is not None and rc.status == "fail" and rc.level == "warning"


def test_field_ref_parses_from_dict_operands():
    # L1Check coerces dict operands into L1FieldRef
    check = L1Check(
        type="eq", left={"doc": "报价单", "field": "total"}, right="100",
    )
    assert isinstance(check.left, L1FieldRef)
