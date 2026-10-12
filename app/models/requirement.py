from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RequirementSnapshot(Base):
    __tablename__ = "requirement_snapshots"

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "source_sha256",
            name="uq_requirement_snapshot",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(50))

    source_file: Mapped[str] = mapped_column(String(300))
    source_sha256: Mapped[str] = mapped_column(String(64))

    # 明确表示这是从提供的 HTML 中读取的主修要求。
    scope: Mapped[str] = mapped_column(String(100))

    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class RequirementNode(Base):
    __tablename__ = "requirement_nodes"

    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "source_node_id",
            name="uq_requirement_node",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_snapshots.id"),
        index=True,
    )

    source_node_id: Mapped[str] = mapped_column(String(100))
    parent_source_id: Mapped[str | None] = mapped_column(String(100))

    name: Mapped[str] = mapped_column(String(200))

    required_credits: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3)
    )
    earned_credits: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3)
    )

    completion_raw: Mapped[str | None] = mapped_column(String(50))
    relation_raw: Mapped[str | None] = mapped_column(String(50))

    expected_course_count: Mapped[int | None]
    passed_course_count: Mapped[int | None]

    courses: Mapped[list] = mapped_column(JSONB)