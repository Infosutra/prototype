"""DQA rule evaluation against a fixture rule pack."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.domain.dqa.eval import eval_check

FIXTURE_PACK = Path(__file__).resolve().parents[1] / "app" / "rule_packs" / "facility.yml"


def _load_facility_pack() -> dict[str, Any]:
    with FIXTURE_PACK.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _rule_by_id(pack: dict[str, Any], rule_id: str) -> dict[str, Any]:
    for rule in pack.get("rules") or []:
        if rule.get("id") == rule_id:
            return rule
    raise KeyError(rule_id)


def test_facility_required_identifiers_pass():
    pack = _load_facility_pack()
    rule = _rule_by_id(pack, "T1-2")
    data = {
        "Q1": "enum-1",
        "A1": "District",
        "A1b": "Block",
        "A2": "School A",
        "A2b": "12345678901",
    }
    ok, details = eval_check(rule["check"], data=data, pack=pack)
    assert ok is True
    assert details.get("op") == "all"


def test_facility_required_identifiers_fail_when_udise_blank():
    pack = _load_facility_pack()
    rule = _rule_by_id(pack, "T1-2")
    data = {
        "Q1": "enum-1",
        "A1": "District",
        "A1b": "Block",
        "A2": "School A",
        "A2b": "",
    }
    ok, details = eval_check(rule["check"], data=data, pack=pack)
    assert ok is False
    assert details.get("op") == "all"
    assert details.get("failed", {}).get("op") == "required"


def test_facility_udise_regex():
    pack = _load_facility_pack()
    rule = _rule_by_id(pack, "T1-3a")

    ok, _ = eval_check(rule["check"], data={"A2b": "12345678901"}, pack=pack)
    assert ok is True

    ok_bad, details = eval_check(rule["check"], data={"A2b": "123"}, pack=pack)
    assert ok_bad is False
    assert details.get("pattern") == "^\\d{11}$"


def test_facility_consent_if_then():
    pack = _load_facility_pack()
    rule = _rule_by_id(pack, "T1-1")

    # No section data → antecedent false → rule N/A (passes)
    ok_na, _ = eval_check(rule["check"], data={}, pack=pack)
    assert ok_na is True

    # Section filled but consent missing → fails
    data_fail = {"con1/x": "1", "CONSENT": ""}
    ok_fail, details = eval_check(rule["check"], data=data_fail, pack=pack)
    assert ok_fail is False
    assert details.get("op") == "if_then"

    # Section filled with consent yes → passes
    data_ok = {"con1/x": "1", "CONSENT": "1"}
    ok_pass, _ = eval_check(rule["check"], data=data_ok, pack=pack)
    assert ok_pass is True


def test_classroom_area_between_threshold():
    pack = _load_facility_pack()
    rule = _rule_by_id(pack, "T1-5")

    ok, _ = eval_check(rule["check"], data={"C1": "200"}, pack=pack)
    assert ok is True

    ok_low, _ = eval_check(rule["check"], data={"C1": "10"}, pack=pack)
    assert ok_low is False
