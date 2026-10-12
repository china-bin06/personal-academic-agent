import argparse
import json
import re
from pathlib import Path

import pdfplumber


# 用于识别一个新课程块中的节次信息
PERIOD_PATTERN = re.compile(
    r"[（(]\s*\d+\s*[-－—–]\s*\d+\s*节\s*[）)]"
)


def compact(text: str) -> str:
    """去掉 PDF 自动换行产生的空白。"""
    return re.sub(r"\s+", "", text)


def extract_blocks(source: Path) -> dict:
    scheduled = []
    other_courses = []

    # 保存每个星期列最后出现的课程，供跨页续文使用
    last_by_weekday = {}

    academic_year = None
    semester = None

    with pdfplumber.open(source) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""

            if academic_year is None:
                match = re.search(
                    r"(\d{4}-\d{4})学年第(\d+)学期",
                    compact(page_text),
                )

                if match:
                    academic_year = match.group(1)
                    semester = int(match.group(2))

            tables = page.extract_tables()

            if not tables:
                raise ValueError(
                    f"第 {page_number} 页没有检测到表格"
                )

            for table in tables:
                for row in table:
                    if not row:
                        continue

                    first_cell = compact(row[0] or "")

                    if first_cell.startswith("其他课程："):
                        content = first_cell.removeprefix("其他课程：")

                        for item in re.split(r"[;；]", content):
                            if item:
                                other_courses.append({
                                    "source_page": page_number,
                                    "raw_text": item,
                                })

                        continue

                    # 标题、表头、说明行不是课程
                    if (
                        "课表" in first_cell
                        or first_cell == "时间段"
                        or first_cell.startswith("*:")
                        or first_cell.startswith("＊:")
                    ):
                        continue

                    if len(row) != 9:
                        raise ValueError(
                            f"第 {page_number} 页出现非9列表格行："
                            f"{row!r}"
                        )

                    section_cell = compact(row[1] or "")

                    for column_index in range(2, 9):
                        raw_text = row[column_index]

                        if not raw_text or not raw_text.strip():
                            continue

                        text = compact(raw_text)
                        weekday = column_index - 1

                        if PERIOD_PATTERN.search(text):
                            block = {
                                "weekday": weekday,
                                "source_pages": [page_number],
                                "raw_text": text,
                            }

                            scheduled.append(block)
                            last_by_weekday[weekday] = block

                        elif (
                            page_number > 1
                            and not section_cell
                            and weekday in last_by_weekday
                            and last_by_weekday[weekday][
                                "source_pages"
                            ][-1] == page_number - 1
                        ):
                            # 当前 PDF 第二页的跨页续文
                            previous = last_by_weekday[weekday]
                            previous["raw_text"] += text

                            if page_number not in previous["source_pages"]:
                                previous["source_pages"].append(page_number)

                        else:
                            raise ValueError(
                                "无法识别课程或续文："
                                f"第{page_number}页，星期{weekday}，"
                                f"内容={text!r}"
                            )

    if academic_year is None or semester is None:
        raise ValueError("未识别到学年和学期")

    return {
        "source_file": source.name,
        "academic_year": academic_year,
        "semester": semester,
        "scheduled_blocks": scheduled,
        "other_courses": other_courses,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = extract_blocks(Path(args.file))
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"学年：{result['academic_year']}")
    print(f"学期：{result['semester']}")
    print(f"有时间的课程块：{len(result['scheduled_blocks'])}")
    print(f"其他课程：{len(result['other_courses'])}")
    print(f"输出文件：{target}")


if __name__ == "__main__":
    main()