from decimal import Decimal

from pydantic import BaseModel, Field


class RequirementCourseInput(BaseModel):
    source_course_id: str = Field(min_length=1)
    course_code: str = Field(min_length=1)
    course_name: str = Field(min_length=1)

    credits: Decimal = Field(
        ge=0,
        max_digits=10,
        decimal_places=3,
    )

    # 使用页面文字，不将“已修”自动等同于“已通过”。
    study_status: str

    # 保留原始表格字段，包含成绩、补考、重修等。
    raw_cells: list[str]


class RequirementNodeInput(BaseModel):
    source_node_id: str = Field(min_length=1)
    parent_source_id: str | None
    name: str = Field(min_length=1, max_length=200)

    required_credits: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=10,
        decimal_places=3,
    )
    earned_credits: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=10,
        decimal_places=3,
    )

    completion_raw: str | None = None
    relation_raw: str | None = None

    expected_course_count: int | None = Field(default=None, ge=0)
    passed_course_count: int | None = Field(default=None, ge=0)

    courses: list[RequirementCourseInput] = Field(default_factory=list)