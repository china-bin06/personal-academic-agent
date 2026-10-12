from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class TermParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    academic_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    semester: int = Field(strict=True, ge=1, le=3)

    @field_validator("academic_year")
    @classmethod
    def validate_year(cls, value):
        start, end = map(int, value.split("-"))

        if end != start + 1:
            raise ValueError("学年必须为连续两年")

        return value


class GradeSummaryParams(TermParams):
    lowest_count: int = Field(default=3, strict=True, ge=1, le=10)


class CompareTermsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first: TermParams
    second: TermParams

    @model_validator(mode="after")
    def validate_terms(self):
        if self.first == self.second:
            raise ValueError("请选择两个不同的学期")

        return self


class ScheduleParams(TermParams):
    week: int = Field(strict=True, ge=1, le=60)
    weekday: int | None = Field(
        default=None,
        strict=True,
        ge=1,
        le=7,
    )


class DegreeProgressParams(BaseModel):
    model_config = ConfigDict(extra="forbid")