from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.schedule import (
    ScheduleCourse,
    ScheduleMeeting,
    ScheduleSnapshot,
)
from app.schemas.schedule import ScheduleInput


def import_schedule_snapshot(
    data: ScheduleInput,
    file_path: Path,
    source_sha256: str,
    owner_id: str = "local",
):
    with Session(engine) as session:
        with session.begin():
            existing_id = session.scalar(
                select(ScheduleSnapshot.id).where(
                    ScheduleSnapshot.owner_id == owner_id,
                    ScheduleSnapshot.source_sha256 == source_sha256,
                )
            )

            if existing_id is not None:
                return {
                    "status": "unchanged",
                    "snapshot_id": existing_id,
                }

            snapshot = ScheduleSnapshot(
                owner_id=owner_id,
                academic_year=data.academic_year,
                semester=data.semester,
                source_file=file_path.name,
                source_sha256=source_sha256,
                source_note=data.source_note,
            )

            session.add(snapshot)
            session.flush()

            meeting_count = 0

            for item in data.courses:
                course = ScheduleCourse(
                    snapshot_id=snapshot.id,
                    **item.model_dump(exclude={"meetings"}),
                )

                session.add(course)
                session.flush()

                for meeting in item.meetings:
                    session.add(
                        ScheduleMeeting(
                            course_id=course.id,
                            **meeting.model_dump(),
                        )
                    )
                    meeting_count += 1

            result = {
                "status": "created",
                "snapshot_id": snapshot.id,
                "course_count": len(data.courses),
                "meeting_count": meeting_count,
            }

    return result