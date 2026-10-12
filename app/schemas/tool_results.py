from decimal import Decimal

from pydantic import BaseModel, Field

from datetime import datetime, date
from typing import Literal

class LowestCourse(BaseModel):
    course_code: str
    course_name: str
    score: Decimal = Field(ge=0, le=100)


class GradeSummaryResult(BaseModel):
    academic_year: str
    semester: int

    total_records: int = Field(ge=0)
    included_records: int = Field(ge=0)

    excluded: dict[str, int]
    average: Decimal | None
    median: Decimal | None
    maximum: Decimal | None
    minimum: Decimal | None
    distribution: dict[str, int]

    highest_courses: list[LowestCourse]
    lowest_courses: list[LowestCourse]
    source_files: list[str]
    rule: str


class CompareTermsResult(BaseModel):
    first: GradeSummaryResult
    second: GradeSummaryResult
    average_difference: Decimal | None
    note: str


class ScheduleItem(BaseModel):
    course_name: str
    course_code: str | None
    teaching_type: str
    weekday: int = Field(ge=1, le=7)
    period_start: int = Field(ge=1, le=11)
    period_end: int = Field(ge=1, le=11)
    location: str | None


class ScheduleResult(BaseModel):
    snapshot_id: int | None
    imported_at: datetime | None = None
    source_note: str | None = None

    items: list[ScheduleItem]
    unscheduled_courses: list[str]
    note: str


class DateScheduleResult(ScheduleResult):
    resolution_status: Literal["resolved", "needs_configuration", "out_of_term"]
    target_date: date
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    academic_year: str | None = None
    semester: int | None = None
    week: int | None = Field(default=None, ge=1, le=60)
    weekday: int = Field(ge=1, le=7)
    first_monday: date | None = None
    calendar_updated_at: datetime | None = None


class DegreeProgressNode(BaseModel):
    node_id: str
    parent_id: str | None
    name: str

    required_credits: Decimal | None
    earned_credits: Decimal | None
    credit_shortfall: Decimal | None

    completion_raw: str | None
    relation_raw: str | None


class DegreeProgressResult(BaseModel):
    snapshot_id: int | None
    imported_at: datetime | None = None
    scope: str | None = None

    nodes: list[DegreeProgressNode]
    note: str
