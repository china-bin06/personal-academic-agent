import argparse
import json
from decimal import Decimal
from pathlib import Path

from app.schemas.schedule import ScheduleInput


TEACHING_TYPES = {
    "*": "理论",
    "&": "实验",
    "#": "实践",
}


def read_json(path: Path):
    return json.loads(
        path.read_text(encoding="utf-8-sig")
    )


def build_candidate(
    normalized: dict,
    reference: ScheduleInput,
    reference_path: Path,
) -> ScheduleInput:
    if (
        normalized["academic_year"] != reference.academic_year
        or normalized["semester"] != reference.semester
    ):
        raise ValueError("解析文件与参考课表的学年、学期不一致")

    reference_by_code = {
        course.course_code: course
        for course in reference.courses
        if course.course_code
    }

    reference_by_name = {}

    for course in reference.courses:
        reference_by_name.setdefault(
            course.course_name, []
        ).append(course)

    courses = {}

    # 有明确上课时间的课程
    for record in normalized["scheduled_records"]:
        code = record["course_code"]
        original = reference_by_code.get(code)

        if original is None:
            raise ValueError(
                f"参考课表中找不到课程代码：{code}"
            )

        if original.course_name != record["course_name"]:
            raise ValueError(
                f"课程名称不一致：{code}，"
                f"参考={original.course_name}，"
                f"解析={record['course_name']}"
            )

        credits = Decimal(record["credits"])

        if credits != original.credits:
            raise ValueError(
                f"课程学分不一致：{original.course_name}，"
                f"参考={original.credits}，解析={credits}"
            )

        marker = record["teaching_marker"]

        if marker not in TEACHING_TYPES:
            raise ValueError(f"未知教学环节标记：{marker}")

        key = original.course_key

        if key not in courses:
            courses[key] = {
                "course_key": key,
                "course_code": code,
                "course_name": record["course_name"],
                "credits": str(credits),
                "meetings": [],
            }

        courses[key]["meetings"].append({
            "teaching_type": TEACHING_TYPES[marker],
            "weekday": record["weekday"],
            "period_start": record["period_start"],
            "period_end": record["period_end"],
            "weeks": record["weeks"],
            "location": record["location"],
        })

    # PDF 没有明确上课时间的课程
    for record in normalized["other_courses"]:
        name = record["course_name"]
        matches = reference_by_name.get(name, [])

        if len(matches) != 1:
            raise ValueError(
                f"其他课程无法唯一匹配参考课表：{name}"
            )

        original = matches[0]
        key = original.course_key

        if key in courses:
            raise ValueError(
                f"其他课程与已解析课程重复：{name}"
            )

        courses[key] = {
            "course_key": key,
            "course_code": original.course_code,
            "course_name": original.course_name,
            "credits": str(original.credits),
            "meetings": [],
        }

    # 本次转换应覆盖参考课表的全部课程
    reference_keys = {
        course.course_key
        for course in reference.courses
    }

    candidate_keys = set(courses)

    if candidate_keys != reference_keys:
        missing = sorted(reference_keys - candidate_keys)
        extra = sorted(candidate_keys - reference_keys)

        raise ValueError(
            f"课程集合不一致：缺少={missing}，多出={extra}"
        )

    ordered_courses = sorted(
        courses.values(),
        key=lambda course: (
            course["course_code"] or "",
            course["course_key"],
        ),
    )

    for course in ordered_courses:
        course["meetings"].sort(
            key=lambda meeting: (
                meeting["weekday"],
                meeting["period_start"],
                meeting["period_end"],
                meeting["teaching_type"],
                tuple(meeting["weeks"]),
            )
        )

    payload = {
        "academic_year": normalized["academic_year"],
        "semester": normalized["semester"],
        "source_note": (
            f"PDF解析：{normalized['source_file']}；"
            f"课程标识及未排课课程学分参考："
            f"{reference_path.name}"
        ),
        "courses": ordered_courses,
    }

    return ScheduleInput.model_validate(payload)


def main():
    parser = argparse.ArgumentParser(
        description="生成符合导入模型的课表候选JSON"
    )

    parser.add_argument("--file", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source_path = Path(args.file)
    reference_path = Path(args.reference)
    target_path = Path(args.output)

    paths = [
        source_path.resolve(),
        reference_path.resolve(),
        target_path.resolve(),
    ]

    if len(set(paths)) != 3:
        raise SystemExit(
            "输入、参考、输出路径必须不同，避免覆盖原文件"
        )

    try:
        normalized = read_json(source_path)

        reference = ScheduleInput.model_validate(
            read_json(reference_path)
        )

        candidate = build_candidate(
            normalized,
            reference,
            reference_path,
        )

        target_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target_path.write_text(
            json.dumps(
                candidate.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(f"转换失败：{error}") from None

    meeting_count = sum(
        len(course.meetings)
        for course in candidate.courses
    )

    unscheduled_count = sum(
        not course.meetings
        for course in candidate.courses
    )

    print(f"课程数：{len(candidate.courses)}")
    print(f"上课安排数：{meeting_count}")
    print(f"时间未明确课程数：{unscheduled_count}")
    print("ScheduleInput 校验通过")
    print(f"输出文件：{target_path}")


if __name__ == "__main__":
    main()