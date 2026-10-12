from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.requirement import (
    RequirementNode,
    RequirementSnapshot,
)
from app.schemas.tool_params import DegreeProgressParams


def get_degree_progress(
    session: Session,
    params: DegreeProgressParams,
    owner_id: str,
):
    snapshot = session.scalar(
        select(RequirementSnapshot)
        .where(RequirementSnapshot.owner_id == owner_id)
        .order_by(
            RequirementSnapshot.imported_at.desc(),
            RequirementSnapshot.id.desc(),
        )
        .limit(1)
    )

    if snapshot is None:
        return {
            "snapshot_id": None,
            "nodes": [],
            "note": "尚未导入培养计划",
        }

    nodes = session.scalars(
        select(RequirementNode)
        .where(RequirementNode.snapshot_id == snapshot.id)
        .order_by(RequirementNode.id)
        .limit(501)
    ).all()

    if len(nodes) > 500:
        raise ValueError("培养计划节点超过工具允许范围")

    result = []

    for node in nodes:
        shortfall = None

        if (
            node.required_credits is not None
            and node.earned_credits is not None
        ):
            shortfall = max(
                node.required_credits - node.earned_credits,
                Decimal("0"),
            )

        result.append(
            {
                "node_id": node.source_node_id,
                "parent_id": node.parent_source_id,
                "name": node.name,
                "required_credits": node.required_credits,
                "earned_credits": node.earned_credits,
                "credit_shortfall": shortfall,
                "completion_raw": node.completion_raw,
                "relation_raw": node.relation_raw,
            }
        )

    return {
        "snapshot_id": snapshot.id,
        "imported_at": snapshot.imported_at,
        "scope": snapshot.scope,
        "nodes": result,
        "note": (
            "各节点分别展示，不重复累计父子学分；"
            "credit_shortfall只是学分差值，"
            "不代表全部毕业条件是否满足"
        ),
    }