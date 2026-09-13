from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.project import Project
    from app.db.models.study import Study


class DqaRelationship(Base):
    """Study-scoped join between two form projects for inter-form DQA."""

    __tablename__ = "dqa_relationships"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    study_id: Mapped[str] = mapped_column(
        ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    target_project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_join_field: Mapped[str] = mapped_column(String, nullable=False)
    target_join_field: Mapped[str] = mapped_column(String, nullable=False)
    # one: require exactly one match; flag if ambiguous. latest: pick newest if many.
    cardinality: Mapped[str] = mapped_column(String, nullable=False, default="one")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    study: Mapped[Study] = relationship(back_populates="dqa_relationships")
    source_project: Mapped[Project] = relationship(foreign_keys=[source_project_id])
    target_project: Mapped[Project] = relationship(foreign_keys=[target_project_id])

    __table_args__ = (
        UniqueConstraint("study_id", "code", name="dqa_relationships_study_code_uidx"),
        Index("dqa_relationships_study_idx", "study_id"),
    )


class RulePack(Base):
    __tablename__ = "rule_packs"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    pack: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RulePackVersion(Base):
    """Immutable snapshot of a rule pack for audit and reproducibility."""

    __tablename__ = "rule_pack_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    pack: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # active | superseded
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    # manual | compile | seed
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    compile_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("project_id", "version", name="rule_pack_versions_project_version_uidx"),
        Index("rule_pack_versions_project_idx", "project_id"),
    )


class DqaCompileSession(Base):
    """Audit trail for LLM DQA rule compilation."""

    __tablename__ = "dqa_compile_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    study_id: Mapped[str | None] = mapped_column(
        ForeignKey("studies.id", ondelete="SET NULL"), nullable=True
    )
    # success | needs_clarification | invalid | error
    status: Mapped[str] = mapped_column(String, nullable=False)
    english: Mapped[str] = mapped_column(Text, nullable=False, default="")
    conversation_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider: Mapped[str] = mapped_column(String, nullable=False, default="")
    model: Mapped[str] = mapped_column(String, nullable=False, default="")
    prompt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_valid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation_errors: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rule_id: Mapped[str | None] = mapped_column(String, nullable=True)
    rule_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    preview_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("dqa_compile_sessions_project_idx", "project_id"),
        Index("dqa_compile_sessions_status_idx", "status"),
    )

class TriangulationView(Base):
    """Study-defined triangulation view (cross-form join or claim vs observation)."""

    __tablename__ = "triangulation_views"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    study_id: Mapped[str] = mapped_column(
        ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    study: Mapped[Study] = relationship(back_populates="triangulation_views")

    __table_args__ = (
        UniqueConstraint("study_id", "code", name="triangulation_views_study_code_uidx"),
        Index("triangulation_views_study_idx", "study_id"),
    )


class DqaFlag(Base):
    __tablename__ = "dqa_flags"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalized from project/submission study at flag write.
    study_id: Mapped[str | None] = mapped_column(String, nullable=True)
    rule_id: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False, default="amber")
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("dqa_flags_project_idx", "project_id"),
        Index("dqa_flags_submission_idx", "submission_id"),
        Index("dqa_flags_severity_idx", "severity"),
        Index("dqa_flags_study_idx", "study_id"),
        UniqueConstraint("submission_id", "rule_id", name="dqa_flags_submission_rule_uidx"),
    )
