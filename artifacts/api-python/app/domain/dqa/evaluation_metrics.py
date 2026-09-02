"""Evaluation metrics for DQA observability."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvaluationMetrics:
    duration_ms: float = 0.0
    submissions: int = 0
    rules_evaluated: int = 0
    flags_produced: int = 0
    flagged_submissions: int = 0
    relationship_lookups: int = 0
    relationship_lookup_ms: float = 0.0
    evaluation_errors: list[str] = field(default_factory=list)
    rule_timings_ms: dict[str, float] = field(default_factory=dict)
    cascade_projects: list[str] = field(default_factory=list)
    pack_version: int | None = None

    def to_dict(self) -> dict[str, Any]:
        slow_rules = sorted(
            self.rule_timings_ms.items(), key=lambda item: item[1], reverse=True
        )[:10]
        return {
            "duration_ms": round(self.duration_ms, 2),
            "submissions": self.submissions,
            "rules_evaluated": self.rules_evaluated,
            "flags_produced": self.flags_produced,
            "flagged_submissions": self.flagged_submissions,
            "relationship_lookups": self.relationship_lookups,
            "relationship_lookup_ms": round(self.relationship_lookup_ms, 2),
            "evaluation_errors": list(self.evaluation_errors),
            "slow_rules": [{"rule_id": rid, "ms": round(ms, 2)} for rid, ms in slow_rules],
            "cascade_projects": list(self.cascade_projects),
            "pack_version": self.pack_version,
        }

    def merge(self, other: EvaluationMetrics) -> None:
        self.duration_ms += other.duration_ms
        self.submissions += other.submissions
        self.rules_evaluated += other.rules_evaluated
        self.flags_produced += other.flags_produced
        self.flagged_submissions += other.flagged_submissions
        self.relationship_lookups += other.relationship_lookups
        self.relationship_lookup_ms += other.relationship_lookup_ms
        self.evaluation_errors.extend(other.evaluation_errors)
        for rule_id, ms in other.rule_timings_ms.items():
            self.rule_timings_ms[rule_id] = self.rule_timings_ms.get(rule_id, 0.0) + ms
