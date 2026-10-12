import json

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.db.read_session import read_engine
from app.schemas.tool_params import (
    GradeSummaryParams,
    ScheduleParams,
    DegreeProgressParams,
)
from app.tools.grades import get_grade_summary
from app.tools.schedules import get_schedule
from app.tools.requirements import get_degree_progress


def show(name, result):
    print(f"\n{name}")
    print(
        json.dumps(
            jsonable_encoder(result),
            ensure_ascii=False,
            indent=2,
        )
    )


with Session(read_engine) as session:
    show(
        "成绩汇总",
        get_grade_summary(
            session,
            GradeSummaryParams(
                academic_year="2025-2026",
                semester=2,
            ),
            owner_id="local",
        ),
    )

    show(
        "第2周星期五",
        get_schedule(
            session,
            ScheduleParams(
                academic_year="2026-2027",
                semester=1,
                week=2,
                weekday=5,
            ),
            owner_id="local",
        ),
    )

    show(
        "培养计划进度",
        get_degree_progress(
            session,
            DegreeProgressParams(),
            owner_id="local",
        ),
    )

read_engine.dispose()