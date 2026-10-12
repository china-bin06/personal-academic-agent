from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook

from app.schemas.grade import GradeInput


REQUIRED_COLUMNS = {
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
}


def clean_text(value) -> str:
    if value is None:
        return ""

    return str(value).strip()


def parse_yes_no(value) -> bool:
    text = clean_text(value)

    if text == "是":
        return True

    if text == "否":
        return False

    raise ValueError("是否成绩作废必须为“是”或“否”")


def parse_score(value) -> tuple[str | None, Decimal | None]:
    text = clean_text(value)

    if not text:
        return None, None

    try:
        number = Decimal(text)
    except InvalidOperation:
        # 等级成绩或其他描述保留原文，不自行换算。
        return text, None

    if not number.is_finite():
        raise ValueError("成绩不能为NaN或无穷值")

    return text, number


def parse_grades_excel(file_path: Path):
    workbook = load_workbook(
        file_path,
        read_only=True,
        data_only=True,
    )

    records = []
    errors = []
    seen_keys = set()

    try:
        if "sheet1" not in workbook.sheetnames:
            raise ValueError("未找到sheet1工作表")

        sheet = workbook["sheet1"]

        # 平台导出的工作表范围可能不准确。
        # 重置后，让只读解析器读取实际存在的行和列。
        sheet.reset_dimensions()

        rows = sheet.iter_rows(values_only=True)

        first_row = next(rows, None)

        if first_row is None:
            raise ValueError("工作表为空")

        headers = [clean_text(value) for value in first_row]

        nonempty_headers = [name for name in headers if name]

        if len(nonempty_headers) != len(set(nonempty_headers)):
            raise ValueError("表头存在重复列名")

        missing = REQUIRED_COLUMNS - set(headers)

        if missing:
            raise ValueError(
                f"缺少必需列：{', '.join(sorted(missing))}"
            )

        for row_number, values in enumerate(rows, start=2):
            if all(clean_text(value) == "" for value in values):
                continue

            row = dict(zip(headers, values))

            try:
                score_raw, score_percent = parse_score(row["成绩"])

                record = GradeInput(
                    student_id=clean_text(row["学号"]),
                    academic_year=clean_text(row["学年"]),
                    semester=clean_text(row["学期"]),
                    course_code=clean_text(row["课程代码"]),
                    course_name=clean_text(row["课程名称"]),
                    course_nature=clean_text(row["课程性质"]),
                    course_category=clean_text(row["课程类别"]),
                    credits=clean_text(row["学分"]),
                    score_raw=score_raw,
                    score_percent=score_percent,
                    exam_nature=clean_text(row["成绩性质"]),
                    is_void=parse_yes_no(row["是否成绩作废"]),
                    teaching_class=clean_text(row["教学班"]),
                )

                key = (
                    record.academic_year,
                    record.semester,
                    record.course_code,
                    record.exam_nature,
                    record.teaching_class,
                )

                if key in seen_keys:
                    raise ValueError("同一文件中出现重复成绩标识")

                seen_keys.add(key)
                records.append(record)

            except ValueError as error:
                errors.append(
                    {
                        "row": row_number,
                        "message": str(error),
                    }
                )

    finally:
        workbook.close()

    if not records and not errors:
        raise ValueError("文件中没有成绩记录")

    return records, errors