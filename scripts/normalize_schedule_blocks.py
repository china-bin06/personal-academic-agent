import argparse
import json
import re
from decimal import Decimal
from pathlib import Path


SCHEDULE_PATTERN = re.compile(
    r"^(?P<name>.+?)"
    r"(?P<marker>[*&#])"
    r"\((?P<start>\d+)-(?P<end>\d+)节\)"
    r"(?P<week_start>\d+)-(?P<week_end>\d+)周"
    r"(?:\((?P<parity>单|双)\))?"
    r"(?=/)"
)

OTHER_PATTERN = re.compile(
    r"^(?P<name>.+?)"
    r"(?P<marker>[*&#])"
    r"(?P<teacher>.+?)"
    r"\(共(?P<total_weeks>\d+)周\)"
    r"/(?P<week_start>\d+)-(?P<week_end>\d+)周"
    r"/无$"
)


def expand_weeks(start: int, end: int, parity=None) -> list[int]:
    if start < 1 or end < start:
        raise ValueError(f"周次范围不合法：{start}-{end}")

    weeks = list(range(start, end + 1))

    if parity == "单":
        weeks = [week for week in weeks if week % 2 == 1]
    elif parity == "双":
        weeks = [week for week in weeks if week % 2 == 0]

    return weeks


def get_field(text: str, label: str) -> str:
    match = re.search(
        rf"/{re.escape(label)}:([^/]*)",
        text,
    )

    if match is None or not match.group(1):
        raise ValueError(f"缺少字段：{label}")

    return match.group(1)


def parse_scheduled(block: dict) -> dict:
    text = block["raw_text"]
    match = SCHEDULE_PATTERN.match(text)

    if match is None:
        raise ValueError(f"无法解析课程时间：{text}")

    weekday = block["weekday"]
    period_start = int(match["start"])
    period_end = int(match["end"])

    if not 1 <= weekday <= 7:
        raise ValueError(f"星期不合法：{weekday}")

    if period_start < 1 or period_end < period_start:
        raise ValueError(
            f"节次不合法：{period_start}-{period_end}"
        )

    teaching_class = get_field(text, "教学班")

    # 从教学班末尾获取课程代码和班次，保留完整教学班文本
    class_match = re.search(
        r"\)-(?P<code>[A-Za-z0-9]+)-"
        r"(?P<section>[A-Za-z0-9]+)$",
        teaching_class,
    )

    if class_match is None:
        raise ValueError(
            f"无法识别课程代码：{teaching_class}"
        )

    credits = Decimal(get_field(text, "学分"))

    if not credits.is_finite() or credits < 0:
        raise ValueError("学分不合法")

    return {
        "course_code": class_match["code"],
        "course_name": match["name"],
        "credits": str(credits),
        "teaching_marker": match["marker"],
        "teaching_class": teaching_class,
        "section": class_match["section"],
        "teacher": get_field(text, "教师"),
        "campus": get_field(text, "校区"),
        "location": get_field(text, "场地"),
        "weekday": weekday,
        "period_start": period_start,
        "period_end": period_end,
        "weeks": expand_weeks(
            int(match["week_start"]),
            int(match["week_end"]),
            match["parity"],
        ),
        "source_pages": block["source_pages"],
        "raw_text": text,
    }


def parse_other(item: dict) -> dict:
    text = item["raw_text"]
    match = OTHER_PATTERN.fullmatch(text)

    if match is None:
        raise ValueError(f"无法解析其他课程：{text}")

    weeks = expand_weeks(
        int(match["week_start"]),
        int(match["week_end"]),
    )

    if len(weeks) != int(match["total_weeks"]):
        raise ValueError(f"其他课程周数不一致：{text}")

    return {
        "course_name": match["name"],
        "teaching_marker": match["marker"],
        "teacher": match["teacher"],
        "course_code": None,
        "credits": None,
        "weeks": weeks,
        "meetings": [],
        "source_page": item["source_page"],
        "raw_text": text,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        payload = json.loads(
            Path(args.file).read_text(encoding="utf-8-sig")
        )

        result = {
            "source_file": payload["source_file"],
            "academic_year": payload["academic_year"],
            "semester": payload["semester"],
            "scheduled_records": [
                parse_scheduled(block)
                for block in payload["scheduled_blocks"]
            ],
            "other_courses": [
                parse_other(item)
                for item in payload["other_courses"]
            ],
        }

        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)

        target.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(f"转换失败：{error}") from None

    print(f"已解析课程块：{len(result['scheduled_records'])}")
    print(f"已解析其他课程：{len(result['other_courses'])}")
    print(f"输出文件：{target}")


if __name__ == "__main__":
    main()