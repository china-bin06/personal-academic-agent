from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.schedule import (
    ScheduleCourse,
    ScheduleMeeting,
    ScheduleSnapshot,
)
from app.schemas.tool_params import ScheduleParams


def get_schedule(
    session: Session,
    params: ScheduleParams,
    owner_id: str,
):
    snapshot = session.scalar(
        select(ScheduleSnapshot)
        .where(
            ScheduleSnapshot.owner_id == owner_id,
            ScheduleSnapshot.academic_year == params.academic_year,
            ScheduleSnapshot.semester == params.semester,
        )
        .order_by(
            ScheduleSnapshot.imported_at.desc(),
            ScheduleSnapshot.id.desc(),
        )
        .limit(1)
    )

    if snapshot is None:
        return {
            "snapshot_id": None,
            "items": [],
            "unscheduled_courses": [],
            "note": "该学期尚未导入课表",
        }

    courses = session.scalars(
        select(ScheduleCourse)
        .where(ScheduleCourse.snapshot_id == snapshot.id)
        .order_by(ScheduleCourse.id)
        .limit(201)
    ).all()

    if len(courses) > 200:
        raise ValueError("课程数量超过工具允许范围")

    meetings = session.scalars(
        select(ScheduleMeeting)
        .join(
            ScheduleCourse,
            ScheduleMeeting.course_id == ScheduleCourse.id,
        )
        .where(ScheduleCourse.snapshot_id == snapshot.id)
        .limit(501)
    ).all()

    if len(meetings) > 500:
        raise ValueError("上课安排超过工具允许范围")

    course_by_id = {course.id: course for course in courses}
    scheduled_ids = {meeting.course_id for meeting in meetings}

    items = []

    for meeting in meetings:
        if params.week not in meeting.weeks:
            continue

        if (
            params.weekday is not None
            and meeting.weekday != params.weekday
        ):
            continue

        course = course_by_id[meeting.course_id]

        items.append(
            {
                "course_name": course.course_name,
                "course_code": course.course_code,
                "teaching_type": meeting.teaching_type,
                "weekday": meeting.weekday,
                "period_start": meeting.period_start,
                "period_end": meeting.period_end,
                "location": meeting.location,
            }
        )

    items.sort(
        key=lambda item: (
            item["weekday"],
            item["period_start"],
            item["course_name"],
        )
    )

    return {
        "snapshot_id": snapshot.id,
        "imported_at": snapshot.imported_at,
        "source_note": snapshot.source_note,
        "items": items,
        "unscheduled_courses": [
            course.course_name
            for course in courses
            if course.id not in scheduled_ids
        ],
        "note": "按常规课表查询，未纳入节假日或临时调课",
    }