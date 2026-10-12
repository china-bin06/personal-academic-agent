from decimal import Decimal, ROUND_HALF_UP
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.grade import Grade
from app.schemas.tool_params import (
    CompareTermsParams,
    GradeSummaryParams,
)

from app.schemas.tool_results import GradeSummaryResult

def round_score(value):
    if value is None:
        return None

    return Decimal(value).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def get_grade_summary(
    session: Session,
    params: GradeSummaryParams,
    owner_id: str,
):
    records = session.scalars(
        select(Grade)
        .where(
            Grade.owner_id == owner_id,
            Grade.academic_year == params.academic_year,
            Grade.semester == params.semester,
        )
        .order_by(Grade.course_code, Grade.id)
        .limit(501)
    ).all()

    if len(records) > 500:
        raise ValueError("单学期记录超过500条，需要检查数据范围")

    eligible = []
    excluded = {
        "void": 0,
        "special_exam": 0,
        "missing_or_non_numeric": 0,
    }

    for record in records:
        if record.is_void:
            excluded["void"] += 1
        elif record.exam_nature != "正常考试":
            excluded["special_exam"] += 1
        elif record.score_percent is None:
            excluded["missing_or_non_numeric"] += 1
        else:
            eligible.append(record)

    scores = [record.score_percent for record in eligible]

    average = (
        sum(scores, Decimal("0")) / len(scores)
        if scores
        else None
    )

    maximum = max(scores) if scores else None
    minimum = min(scores) if scores else None

    highest = sorted(
        [
            record
            for record in eligible
            if record.score_percent == maximum
        ],
        key=lambda record: record.course_code,
    )

    lowest = sorted(
        [
            record
            for record in eligible
            if record.score_percent == minimum
        ],
        key=lambda record: record.course_code,
    )

    distribution = {
        "below_60": sum(score < 60 for score in scores),
        "60_to_69": sum(60 <= score < 70 for score in scores),
        "70_to_79": sum(70 <= score < 80 for score in scores),
        "80_to_89": sum(80 <= score < 90 for score in scores),
        "90_to_100": sum(score >= 90 for score in scores),
    }

    result = {
        "academic_year": params.academic_year,
        "semester": params.semester,
        "total_records": len(records),
        "included_records": len(scores),
        "excluded": excluded,
        "average": round_score(average),
        "median": round_score(median(scores)) if scores else None,
        "maximum": round_score(maximum),
        "minimum": round_score(minimum),
        "distribution": distribution,
        "highest_courses": [
            {
                "course_code": record.course_code,
                "course_name": record.course_name,
                "score": record.score_percent,
            }
            for record in highest
        ],
        "lowest_courses": [
            {
                "course_code": record.course_code,
                "course_name": record.course_name,
                "score": record.score_percent,
            }
            for record in lowest
        ],
        "source_files": sorted(
            {record.source_file for record in records}
        ),
        "rule": "百分制、非作废、正常考试；简单平均，不按学分加权",
    }

    return GradeSummaryResult.model_validate(result).model_dump()

def compare_terms(
    session: Session,
    params: CompareTermsParams,
    owner_id: str,
):
    first = get_grade_summary(
        session,
        GradeSummaryParams(**params.first.model_dump()),
        owner_id,
    )

    second = get_grade_summary(
        session,
        GradeSummaryParams(**params.second.model_dump()),
        owner_id,
    )

    difference = None

    if first["average"] is not None and second["average"] is not None:
        difference = round_score(
            second["average"] - first["average"]
        )

    return {
        "first": first,
        "second": second,
        "average_difference": difference,
        "note": (
            "差值为第二个学期减第一个学期；"
            "两学期课程可能不同，不能仅据此判断能力变化"
        ),
    }