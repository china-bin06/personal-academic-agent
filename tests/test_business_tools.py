from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.grade import Grade
from app.schemas.tool_params import GradeSummaryParams
from app.tools.grades import get_grade_summary
from app.tools import runner


@pytest.fixture
def test_engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'business_test.db'}"
    )

    # 只创建成绩表，避免 PostgreSQL 专用 ARRAY、
    # JSONB 字段影响这个计算测试。
    Grade.__table__.create(engine)

    yield engine

    engine.dispose()


def add_grade(
    session,
    code,
    score,
    *,
    owner_id="local",
    is_void=False,
    exam_nature="正常考试",
    semester=2,
):
    session.add(
        Grade(
            owner_id=owner_id,
            student_id="test-student",
            academic_year="2025-2026",
            semester=semester,
            course_code=code,
            course_name=code,
            course_nature="必修课",
            course_category="测试类别",
            credits=Decimal("2"),
            score_raw=None if score is None else str(score),
            score_percent=(
                None
                if score is None
                else Decimal(str(score))
            ),
            exam_nature=exam_nature,
            is_void=is_void,
            teaching_class="测试班",
            source_file="test.xlsx",
            source_sha256="0" * 64,
        )
    )


def test_grade_calculation_and_exclusions(test_engine):
    with Session(test_engine) as session:
        with session.begin():
            # 0 是有效成绩，不能当作缺失。
            add_grade(session, "A", 0)
            add_grade(session, "B", 60)
            add_grade(session, "C", 80)
            add_grade(session, "D", 100)

            add_grade(session, "E", 90, is_void=True)
            add_grade(session, "F", 90, exam_nature="补考")
            add_grade(session, "G", None)

            # 其他用户的成绩不能混入。
            add_grade(session, "H", 100, owner_id="other")

        result = get_grade_summary(
            session,
            GradeSummaryParams(
                academic_year="2025-2026",
                semester=2,
            ),
            owner_id="local",
        )

    assert result["total_records"] == 7
    assert result["included_records"] == 4
    assert result["average"] == Decimal("60")
    assert result["median"] == Decimal("70")

    assert result["excluded"] == {
        "void": 1,
        "special_exam": 1,
        "missing_or_non_numeric": 1,
    }

    assert result["distribution"]["below_60"] == 1

    assert [
        item["course_code"]
        for item in result["lowest_courses"]
    ] == ["A"]
    assert result["minimum"] == Decimal("0")
    assert result["maximum"] == Decimal("100")
    assert [item["course_code"] for item in result["highest_courses"]] == ["D"]


def test_all_courses_tied_at_extremes_are_returned(test_engine):
    with Session(test_engine) as session:
        with session.begin():
            for code, score in (("A", 60), ("B", 60), ("C", 100), ("D", 100)):
                add_grade(session, code, score)
        result = get_grade_summary(session, GradeSummaryParams(academic_year="2025-2026", semester=2), "local")
    assert [item["course_code"] for item in result["lowest_courses"]] == ["A", "B"]
    assert [item["course_code"] for item in result["highest_courses"]] == ["C", "D"]


def test_empty_term_returns_none(test_engine):
    with Session(test_engine) as session:
        result = get_grade_summary(
            session,
            GradeSummaryParams(
                academic_year="2024-2025",
                semester=1,
            ),
            owner_id="local",
        )

    assert result["included_records"] == 0
    assert result["average"] is None
    assert result["median"] is None


def test_unknown_tool():
    result = runner.run_tool(
        "execute_sql",
        {"sql": "SELECT 1"},
        owner_id="local",
    )

    assert result["status"] == "error"
    assert result["error"]["code"] == "UNKNOWN_TOOL"


def test_invalid_arguments():
    result = runner.run_tool(
        "get_schedule",
        {
            "academic_year": "2026-2027",
            "semester": 1,
            "week": 2,
            "weekday": 8,
        },
        owner_id="local",
    )

    assert result["error"]["code"] == "INVALID_ARGUMENTS"


def test_owner_cannot_be_in_arguments():
    result = runner.run_tool(
        "get_grade_summary",
        {
            "academic_year": "2025-2026",
            "semester": 2,
            "owner_id": "other",
        },
        owner_id="local",
    )

    assert result["error"]["code"] == "INVALID_ARGUMENTS"


def test_runner_success(test_engine, monkeypatch):
    monkeypatch.setattr(runner, "read_engine", test_engine)

    result = runner.run_tool(
        "get_grade_summary",
        {
            "academic_year": "2025-2026",
            "semester": 2,
        },
        owner_id="local",
    )

    assert result["status"] == "success"
    assert result["data"]["average"] is None
    assert result["error"] is None


def test_database_failure_is_not_empty_success(
    test_engine,
    monkeypatch,
):
    monkeypatch.setattr(runner, "read_engine", test_engine)

    def broken_query(session, params, owner_id):
        raise OperationalError(
            None,
            None,
            Exception("internal-sensitive-message"),
        )

    spec = runner.TOOLS["get_grade_summary"]

    monkeypatch.setitem(
        runner.TOOLS,
        "get_grade_summary",
        runner.ToolSpec(
            spec.params_model,
            spec.result_model,
            broken_query,
        ),
    )

    result = runner.run_tool(
        "get_grade_summary",
        {
            "academic_year": "2025-2026",
            "semester": 2,
        },
        owner_id="local",
    )

    assert result["status"] == "error"
    assert result["error"]["code"] == "DATABASE_ERROR"
    assert result["data"] is None

    assert "internal-sensitive-message" not in str(result)


def test_invalid_result_is_rejected(
    test_engine,
    monkeypatch,
):
    monkeypatch.setattr(runner, "read_engine", test_engine)

    spec = runner.TOOLS["get_grade_summary"]

    monkeypatch.setitem(
        runner.TOOLS,
        "get_grade_summary",
        runner.ToolSpec(
            spec.params_model,
            spec.result_model,
            lambda session, params, owner_id: {},
        ),
    )

    result = runner.run_tool(
        "get_grade_summary",
        {
            "academic_year": "2025-2026",
            "semester": 2,
        },
        owner_id="local",
    )

    assert result["error"]["code"] == "INVALID_RESULT"
