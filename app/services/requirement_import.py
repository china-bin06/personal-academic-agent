from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.requirement import (
    RequirementNode,
    RequirementSnapshot,
)
from app.schemas.requirement import RequirementNodeInput


def import_requirement_snapshot(
    nodes: list[RequirementNodeInput],
    file_path: Path,
    source_sha256: str,
    owner_id: str = "local",
):
    if not nodes:
        raise ValueError("没有培养计划节点")

    with Session(engine) as session:
        with session.begin():
            existing_id = session.scalar(
                select(RequirementSnapshot.id).where(
                    RequirementSnapshot.owner_id == owner_id,
                    RequirementSnapshot.source_sha256 == source_sha256,
                )
            )

            if existing_id is not None:
                return {
                    "status": "unchanged",
                    "snapshot_id": existing_id,
                }

            snapshot = RequirementSnapshot(
                owner_id=owner_id,
                source_file=file_path.name,
                source_sha256=source_sha256,
                scope="主修（提供的HTML）",
            )

            session.add(snapshot)
            session.flush()

            for node in nodes:
                payload = node.model_dump(exclude={"courses"})

                session.add(
                    RequirementNode(
                        **payload,
                        snapshot_id=snapshot.id,
                        courses=[
                            course.model_dump(mode="json")
                            for course in node.courses
                        ],
                    )
                )

            result = {
                "status": "created",
                "snapshot_id": snapshot.id,
                "node_count": len(nodes),
                "course_entries": sum(
                    len(node.courses) for node in nodes
                ),
            }

    return result