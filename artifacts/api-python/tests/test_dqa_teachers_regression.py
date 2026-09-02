"""Regression tests for teachers.yml rule pack evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.domain.dqa.eval import eval_check

TEACHERS_PACK = (
    Path(__file__).resolve().parents[1] / "app" / "rule_packs" / "teachers.yml"
)


def _load_teachers_pack() -> dict[str, Any]:
    with TEACHERS_PACK.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_teachers_rules_evaluate_without_error_on_empty_data():
    pack = _load_teachers_pack()
    for rule in pack.get("rules") or []:
        check = rule.get("check")
        assert isinstance(check, dict), rule.get("id")
        ok, _ = eval_check(check, data={}, pack=pack)
        assert isinstance(ok, bool)


def test_teachers_t2_14_duration_min_only():
    pack = _load_teachers_pack()
    rule = next(r for r in pack["rules"] if r["id"] == "T2-14")
    ok_short, details = eval_check(
        rule["check"],
        data={
            "start": "2024-01-01T10:00:00",
            "end": "2024-01-01T10:10:00",
        },
        pack=pack,
    )
    assert ok_short is False
    assert details["minutes"] == 10.0
    assert details["min"] == 20

    ok_long, details_long = eval_check(
        rule["check"],
        data={
            "start": "2024-01-01T10:00:00",
            "end": "2024-01-01T10:30:00",
        },
        pack=pack,
    )
    assert ok_long is True
    assert details_long["minutes"] == 30.0


def test_teachers_t2_1_consent_if_then():
    pack = _load_teachers_pack()
    rule = next(r for r in pack["rules"] if r["id"] == "T2-1")
    ok_na, _ = eval_check(rule["check"], data={}, pack=pack)
    assert ok_na is True

    ok_fail, _ = eval_check(
        rule["check"],
        data={"con1/x": "1", "K_CONSENT": ""},
        pack=pack,
    )
    assert ok_fail is False

    ok_pass, _ = eval_check(
        rule["check"],
        data={"con1/x": "1", "K_CONSENT": "1"},
        pack=pack,
    )
    assert ok_pass is True


def test_teachers_t2_2_required_identifiers():
    pack = _load_teachers_pack()
    rule = next(r for r in pack["rules"] if r["id"] == "T2-2")
    ok, _ = eval_check(
        rule["check"],
        data={"K_ENUM_ID": "e1", "P_RESP_ID": "r1", "K_INST_ID": "123"},
        pack=pack,
    )
    assert ok is True

    ok_fail, details = eval_check(
        rule["check"],
        data={"K_ENUM_ID": "e1", "P_RESP_ID": "r1", "K_INST_ID": ""},
        pack=pack,
    )
    assert ok_fail is False
    assert details.get("failed", {}).get("op") == "required"
