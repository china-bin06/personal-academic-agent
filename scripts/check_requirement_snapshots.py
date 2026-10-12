import hashlib
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.importers.requirements_html import parse_requirements_html
from app.models.requirement import (
    RequirementNode,
    RequirementSnapshot,
)
from app.services.requirement_import import (
    import_requirement_snapshot,
)


def import_file(path, owner_id):
    content = path.read_bytes()
    nodes = parse_requirements_html(
        content.decode("utf-8-sig")
    )

    return import_requirement_snapshot(
        nodes=nodes,
        file_path=path,
        source_sha256=hashlib.sha256(content).hexdigest(),
        owner_id=owner_id,
    )


def main():
    # 每次运行使用新的测试标识，不混入 local 用户。
    owner_id = f"requirements-test-{uuid4().hex[:12]}"

    original = Path("data/requirements/plan.html")
    modified = Path(
        "data/requirements_test/changed_credits.html"
    )

    old_result = import_file(original, owner_id)
    new_result = import_file(modified, owner_id)

    assert old_result["status"] == "created"
    assert new_result["status"] == "created"

    old_id = old_result["snapshot_id"]
    new_id = new_result["snapshot_id"]

    assert old_id != new_id

    target_node_id = "51BDB81E04E84E16E0630C00F80AA47C"

    with Session(engine) as session:
        snapshots = session.scalars(
            select(RequirementSnapshot).where(
                RequirementSnapshot.owner_id == owner_id
            )
        ).all()

        assert len(snapshots) == 2

        old_node = session.scalar(
            select(RequirementNode).where(
                RequirementNode.snapshot_id == old_id,
                RequirementNode.source_node_id == target_node_id,
            )
        )

        new_node = session.scalar(
            select(RequirementNode).where(
                RequirementNode.snapshot_id == new_id,
                RequirementNode.source_node_id == target_node_id,
            )
        )

        assert old_node is not None
        assert new_node is not None

        assert str(old_node.earned_credits) == "22.500"
        assert str(new_node.earned_credits) == "21.500"

    # 再次导入修改后的同一文件，应复用已有快照。
    repeated = import_file(modified, owner_id)

    assert repeated["status"] == "unchanged"
    assert repeated["snapshot_id"] == new_id

    print("测试通过：新旧快照同时保留，重复导入不新增快照")
    print(f"测试用户标识：{owner_id}")
    print(f"旧快照ID：{old_id}")
    print(f"新快照ID：{new_id}")


if __name__ == "__main__":
    main()