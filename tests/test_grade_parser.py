from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.importers.grades_excel import (
    parse_grades_excel,
    parse_score,
    parse_yes_no,
)


HEADERS = [
    "学号",
    "学年",
    "学期",
    "课程代码",
    "课程名称",
    "课程性质",
    "课程类别",
    "学分",
    "成绩",
    "成绩性质",
    "是否成绩作废",
    "教学班",
]


def make_file(tmp_path, score):
    path = tmp_path / "grades.xlsx"

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "sheet1"

    sheet.append(HEADERS)
    sheet.append(
        [
            "test-student",
            "2025-2026",
            "2",
            "TEST001",
            "测试课程",
            "必修课",
            "专业教育课程",
            "2.0",
            score,
            "正常考试",
            "否",
            "测试班",
        ]
    )

    workbook.save(path)
    workbook.close()

    return path


def test_numeric_score():
    assert parse_score("88") == ("88", Decimal("88"))


def test_missing_score_is_not_zero():
    assert parse_score(None) == (None, None)


def test_text_score_is_not_converted():
    assert parse_score("优秀") == ("优秀", None)


def test_yes_no():
    assert parse_yes_no("否") is False

    with pytest.raises(ValueError):
        parse_yes_no("未知")


def test_excel_valid(tmp_path):
    path = make_file(tmp_path, "88")

    records, errors = parse_grades_excel(path)

    assert len(records) == 1
    assert errors == []
    assert records[0].score_percent == Decimal("88")


def test_out_of_range_score(tmp_path):
    path = make_file(tmp_path, "101")

    records, errors = parse_grades_excel(path)

    assert records == []
    assert errors[0]["row"] == 2