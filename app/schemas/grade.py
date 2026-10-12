from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class GradeInput(BaseModel):
    student_id: str = Field(min_length=1, max_length=50)

    academic_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    semester: int = Field(ge=1, le=3)

    course_code: str = Field(min_length=1, max_length=100)
    course_name: str = Field(min_length=1, max_length=200)

    course_nature: str = Field(min_length=1, max_length=50)
    course_category: str = Field(max_length=100)

    credits: Decimal = Field(
        ge=0,
        max_digits=10,
        decimal_places=3,
    )

    score_raw: str | None
    score_percent: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
        max_digits=10,
        decimal_places=3,
    )

    exam_nature: str = Field(min_length=1, max_length=100)
    is_void: bool
    teaching_class: str = Field(max_length=300)

    @field_validator("academic_year")
    @classmethod
    def validate_academic_year(cls, value: str) -> str:
        start, end = map(int, value.split("-"))

        if end != start + 1:
            raise ValueError("学年必须为连续两年，例如2025-2026")

        return value