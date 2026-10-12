import argparse
import hashlib
import json
from pathlib import Path

from app.schemas.schedule import ScheduleInput


def main():
    parser = argparse.ArgumentParser(
        description="预览或导入课表JSON"
    )

    parser.add_argument("--file", required=True)
    parser.add_argument("--preview", action="store_true")

    # 仅用于本地导入工具；默认保存到个人数据。
    parser.add_argument("--owner", default="local")

    args = parser.parse_args()
    file_path = Path(args.file)

    try:
        content = file_path.read_bytes()
        payload = json.loads(content.decode("utf-8-sig"))
        data = ScheduleInput.model_validate(payload)
    except (OSError, UnicodeError, ValueError) as error:
        raise SystemExit(f"解析失败：{error}") from None

    print(
        f"学期：{data.academic_year}-{data.semester}\n"
        f"来源说明：{data.source_note}"
    )

    for course in data.courses:
        print(
            f"\n{course.course_name}"
            f" | 学分={course.credits}"
        )

        if not course.meetings:
            print("  上课时间未明确")
            continue

        for meeting in course.meetings:
            print(
                f"  {meeting.teaching_type}"
                f" | 星期{meeting.weekday}"
                f" | 第{meeting.period_start}"
                f"—{meeting.period_end}节"
                f" | 周次={meeting.weeks}"
                f" | 地点={meeting.location}"
            )

    if args.preview:
        print("\n预览完成，未写入数据库")
        return

    from sqlalchemy.exc import SQLAlchemyError

    from app.services.schedule_import import (
        import_schedule_snapshot,
    )

    try:
        result = import_schedule_snapshot(
            data=data,
            file_path=file_path,
            source_sha256=hashlib.sha256(content).hexdigest(),
            owner_id=args.owner,
        )
    except SQLAlchemyError:
        raise SystemExit(
            "数据库写入失败，事务已回滚；"
            "请检查连接、迁移和是否存在并发导入"
        ) from None

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()