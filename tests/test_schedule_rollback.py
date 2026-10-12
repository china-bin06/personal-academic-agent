import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.schedule import (
    ScheduleCourse,
    ScheduleMeeting,
    ScheduleSnapshot,
)
from app.schemas.schedule import ScheduleInput
from app.services import schedule_import as service


def test_failed_import_preserves_old_snapshot(monkeypatch):
    # 访问真实数据库，仅使用独立测试 owner；保留测试快照。
    owner = f"rollback-{uuid4().hex[:12]}"

    root = Path(__file__).resolve().parents[1]
    path = root / "data/candidates/schedule-2026-2027-1.json"

    content = path.read_bytes()
    data = ScheduleInput.model_validate_json(content)

    first = service.import_schedule_snapshot(
        data=data,
        file_path=path,
        source_sha256=hashlib.sha256(content).hexdigest(),
        owner_id=owner,
    )

    old_id = first["snapshot_id"]

    changed = data.model_copy(
        update={"source_note": "隔离回滚测试"}
    )
    changed_bytes = changed.model_dump_json().encode("utf-8")

    def fail_meeting_creation(*args, **kwargs):
        raise RuntimeError("模拟上课安排写入失败")

    # 快照、课程已 flush 后，在建立上课安排时抛出异常。
    monkeypatch.setattr(
        service,
        "ScheduleMeeting",
        fail_meeting_creation,
    )

    with pytest.raises(RuntimeError):
        service.import_schedule_snapshot(
            data=changed,
            file_path=path,
            source_sha256=hashlib.sha256(
                changed_bytes
            ).hexdigest(),
            owner_id=owner,
        )

    with Session(service.engine) as session:
        ids = session.scalars(
            select(ScheduleSnapshot.id).where(
                ScheduleSnapshot.owner_id == owner
            )
        ).all()

        assert ids == [old_id]

        course_count = session.scalar(
            select(func.count())
            .select_from(ScheduleCourse)
            .where(ScheduleCourse.snapshot_id == old_id)
        )

        meeting_count = session.scalar(
            select(func.count())
            .select_from(ScheduleMeeting)
            .join(
                ScheduleCourse,
                ScheduleMeeting.course_id == ScheduleCourse.id,
            )
            .where(ScheduleCourse.snapshot_id == old_id)
        )

        assert course_count == len(data.courses)
        assert meeting_count == sum(
            len(course.meetings)
            for course in data.courses
        )
