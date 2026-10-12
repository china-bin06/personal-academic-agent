import argparse
import hashlib
import json
from pathlib import Path

from app.importers.requirements_html import (
    parse_requirements_html,
)


def main():
    parser = argparse.ArgumentParser(
        description="预览或导入培养计划HTML"
    )
    parser.add_argument("--file", required=True)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()

    file_path = Path(args.file)

    try:
        file_bytes = file_path.read_bytes()
        html = file_bytes.decode("utf-8-sig")
        nodes = parse_requirements_html(html)
    except (OSError, UnicodeError, ValueError) as error:
        raise SystemExit(f"解析失败：{error}") from None

    depth_by_id = {}

    for node in nodes:
        depth = (
            0
            if node.parent_source_id is None
            else depth_by_id[node.parent_source_id] + 1
        )
        depth_by_id[node.source_node_id] = depth

        required = node.required_credits
        earned = node.earned_credits

        print(
            "  " * depth
            + f"- {node.name}"
            + f" | 要求={required} 获得={earned}"
            + f" | 课程条目={len(node.courses)}"
        )

    if args.preview:
        print("预览完成，未写入数据库")
        return

    from sqlalchemy.exc import SQLAlchemyError

    from app.services.requirement_import import (
        import_requirement_snapshot,
    )

    try:
        result = import_requirement_snapshot(
            nodes=nodes,
            file_path=file_path,
            source_sha256=hashlib.sha256(file_bytes).hexdigest(),
        )
    except SQLAlchemyError:
        raise SystemExit(
            "数据库写入失败，事务已回滚；"
            "请检查连接、迁移和是否存在并发导入"
        ) from None

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()