import argparse
import hashlib
import json
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.importers.grades_excel import parse_grades_excel


def main():
    parser = argparse.ArgumentParser(
        description="预览或导入个人成绩Excel"
    )

    parser.add_argument("--file", required=True)
    parser.add_argument("--preview", action="store_true")

    args = parser.parse_args()
    file_path = Path(args.file)

    if not file_path.is_file():
        raise SystemExit("文件不存在")

    if file_path.suffix.lower() != ".xlsx":
        raise SystemExit("当前仅支持.xlsx文件")

    try:
        records, errors = parse_grades_excel(file_path)
    except (ValueError, OSError) as error:
        raise SystemExit(f"解析失败：{error}") from None

    summary = {
        "valid_records": len(records),
        "error_records": len(errors),
        "terms": sorted(
            {
                f"{record.academic_year}-{record.semester}"
                for record in records
            }
        ),
        "missing_scores": sum(
            record.score_raw is None for record in records
        ),
        "non_numeric_scores": sum(
            record.score_raw is not None
            and record.score_percent is None
            for record in records
        ),
        "void_records": sum(
            record.is_void for record in records
        ),
        "special_exam_records": sum(
            record.exam_nature != "正常考试"
            for record in records
        ),
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if errors:
        print(json.dumps(errors, ensure_ascii=False, indent=2))
        raise SystemExit("存在校验错误，未写入数据库")

    if args.preview:
        print("预览完成，未写入数据库")
        return

    # 预览无需加载数据库配置。
    from app.services.grade_import import import_grades

    file_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()

    try:
        result = import_grades(
            records=records,
            file_path=file_path,
            source_sha256=file_hash,
        )
    except ValueError as error:
        raise SystemExit(f"导入失败：{error}") from None
    except SQLAlchemyError:
        raise SystemExit(
            "数据库写入失败，事务已回滚，请检查数据库连接和表结构"
        ) from None

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()