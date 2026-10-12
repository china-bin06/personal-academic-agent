from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScheduleSnapshot(Base):
    __tablename__ = "schedule_snapshots"

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "source_sha256",
            name="uq_schedule_snapshot",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(50))

    academic_year: Mapped[str] = mapped_column(String(9))
    semester: Mapped[int]

    source_file: Mapped[str] = mapped_column(String(300))
    source_sha256: Mapped[str] = mapped_column(String(64))
    source_note: Mapped[str] = mapped_column(String(500))

    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class ScheduleCourse(Base):
    __tablename__ = "schedule_courses"

    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "course_key",
            name="uq_schedule_course",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("schedule_snapshots.id"),
        index=True,
    )

    course_key: Mapped[str] = mapped_column(String(100))
    course_code: Mapped[str | None] = mapped_column(String(100))
    course_name: Mapped[str] = mapped_column(String(200))
    credits: Mapped[Decimal] = mapped_column(Numeric(10, 3))


class ScheduleMeeting(Base):
    __tablename__ = "schedule_meetings"

    id: Mapped[int] = mapped_column(primary_key=True)

    course_id: Mapped[int] = mapped_column(
        ForeignKey("schedule_courses.id"),
        index=True,
    )

    teaching_type: Mapped[str] = mapped_column(String(20))
    weekday: Mapped[int]
    period_start: Mapped[int]
    period_end: Mapped[int]

    weeks: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    location: Mapped[str | None] = mapped_column(String(200))