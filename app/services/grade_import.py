from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.grade import Grade
from app.schemas.grade import GradeInput


def import_grades(
    records: list[GradeInput],
    file_path: Path,
    source_sha256: str,
    owner_id: str = "local",
):
    if not records:
        raise ValueError("没有可导入记录")

    student_ids = {record.student_id for record in records}

    if len(student_ids) != 1:
        raise ValueError("第一版仅支持单个学生的成绩文件")

    student_id = next(iter(student_ids))

    counts = {
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
    }

    with Session(engine) as session:
        with session.begin():
            existing_students = set(
                session.scalars(
                    select(Grade.student_id)
                    .where(Grade.owner_id == owner_id)
                    .distinct()
                )
            )

            if existing_students - {student_id}:
                raise ValueError(
                    "文件学号与当前用户已有成绩不一致"
                )

            for record in records:
                existing = session.scalar(
                    select(Grade).where(
                        Grade.owner_id == owner_id,
                        Grade.academic_year == record.academic_year,
                        Grade.semester == record.semester,
                        Grade.course_code == record.course_code,
                        Grade.exam_nature == record.exam_nature,
                        Grade.teaching_class == record.teaching_class,
                    )
                )

                payload = record.model_dump()

                if existing is None:
                    session.add(
                        Grade(
                            **payload,
                            owner_id=owner_id,
                            source_file=file_path.name,
                            source_sha256=source_sha256,
                            imported_at=datetime.now(timezone.utc),
                        )
                    )
                    counts["inserted"] += 1
                    continue

                changed = any(
                    getattr(existing, name) != value
                    for name, value in payload.items()
                )

                if not changed:
                    counts["unchanged"] += 1
                    continue

                for name, value in payload.items():
                    setattr(existing, name, value)

                existing.source_file = file_path.name
                existing.source_sha256 = source_sha256
                existing.imported_at = datetime.now(timezone.utc)

                counts["updated"] += 1

    return counts