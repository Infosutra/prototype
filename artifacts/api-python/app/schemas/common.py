from pydantic import BaseModel, ConfigDict, Field


def to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        serialize_by_alias=True,
    )


class OkResponse(CamelModel):
    success: bool = True


# Shared query-parameter models (camelCase on the wire via alias_generator).


class StudyIdQuery(CamelModel):
    study_id: str | None = None


class ProjectIdQuery(CamelModel):
    project_id: str | None = None


class StudyProjectQuery(CamelModel):
    study_id: str | None = None
    project_id: str | None = None


class DqaFlagsQuery(CamelModel):
    project_id: str | None = None
    study_id: str | None = None
    submission_id: str | None = None
    rule_id: str | None = None
    severity: str | None = None
    enumerator: str | None = None
    limit: int = Field(default=500, ge=1, le=2000)


class ReportsListQuery(CamelModel):
    study_id: str | None = None
    report_type: str | None = None


class SubmissionsListQuery(CamelModel):
    project_id: str | None = None
    status: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    page: int = 1
    limit: int = Field(default=20, ge=1, le=200)
