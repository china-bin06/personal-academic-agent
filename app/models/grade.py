from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Grade(Base):
    __tablename__ = "grades"

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "academic_year",
            "semester",
            "course_code",
            "exam_nature",
            "teaching_class",
            name="uq_grade_record",
        ),
        CheckConstraint(
            "credits >= 0",
            name="ck_grade_credits",
        ),
        CheckConstraint(
            "score_percent IS NULL OR "
            "(score_percent >= 0 AND score_percent <= 100)",
            name="ck_grade_score",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    owner_id: Mapped[str] = mapped_column(String(50))
    student_id: Mapped[str] = mapped_column(String(50))

    academic_year: Mapped[str] = mapped_column(String(9))
    semester: Mapped[int]

    course_code: Mapped[str] = mapped_column(String(100))
    course_name: Mapped[str] = mapped_column(String(200))

    course_nature: Mapped[str] = mapped_column(String(50))
    course_category: Mapped[str] = mapped_column(String(100))

    credits: Mapped[Decimal] = mapped_column(Numeric(10, 3))

    score_raw: Mapped[str | None] = mapped_column(String(100))
    score_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3)
    )

    exam_nature: Mapped[str] = mapped_column(String(100))
    is_void: Mapped[bool] = mapped_column(Boolean)

    teaching_class: Mapped[str] = mapped_column(String(300))

    source_file: Mapped[str] = mapped_column(String(300))
    source_sha256: Mapped[str] = mapped_column(String(64))

    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )