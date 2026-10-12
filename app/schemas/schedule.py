from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


WeekNumber = Annotated[int, Field(strict=True, ge=1, le=60)]


class MeetingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    teaching_type: Literal["理论", "实验", "实践", "其他"]

    weekday: int = Field(strict=True, ge=1, le=7)
    period_start: int = Field(strict=True, ge=1, le=11)
    period_end: int = Field(strict=True, ge=1, le=11)

    weeks: list[WeekNumber] = Field(min_length=1)
    location: str | None = Field(default=None, max_length=200)

    @field_validator("weeks")
    @classmethod
    def validate_weeks(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("周次不能重复")

        return sorted(value)

    @model_validator(mode="after")
    def validate_periods(self):
        if self.period_start > self.period_end:
            raise ValueError("起始节次不能大于结束节次")

        return self


class CourseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_key: str = Field(min_length=1, max_length=100)
    course_code: str | None = Field(default=None, max_length=100)
    course_name: str = Field(min_length=1, max_length=200)

    credits: Decimal = Field(
        ge=0,
        max_digits=10,
        decimal_places=3,
    )

    meetings: list[MeetingInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_meetings(self):
        keys = [
            (
                item.teaching_type,
                item.weekday,
                item.period_start,
                item.period_end,
                tuple(item.weeks),
                item.location,
            )
            for item in self.meetings
        ]

        if len(keys) != len(set(keys)):
            raise ValueError("同一课程存在完全重复的上课安排")

        return self


class ScheduleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    academic_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    semester: int = Field(strict=True, ge=1, le=3)

    source_note: str = Field(min_length=1, max_length=500)
    courses: list[CourseInput] = Field(min_length=1)

    @field_validator("academic_year")
    @classmethod
    def validate_academic_year(cls, value):
        start, end = map(int, value.split("-"))

        if end != start + 1:
            raise ValueError("学年必须为连续两年")

        return value

    @model_validator(mode="after")
    def validate_courses(self):
        keys = [course.course_key for course in self.courses]

        if len(keys) != len(set(keys)):
            raise ValueError("course_key不能重复")

        codes = [
            course.course_code
            for course in self.courses
            if course.course_code
        ]

        if len(codes) != len(set(codes)):
            raise ValueError(
                "同一课程代码出现多次，请合并其上课安排"
            )

        return self