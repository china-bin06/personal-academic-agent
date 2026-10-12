from typing import Literal
from urllib.parse import unquote
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.services import data_management as service
from app.schemas.requirement import RequirementCourseInput
from app.schemas.tool_results import DegreeProgressNode

router = APIRouter(prefix="/api/v1", tags=["data-management"])


class ImportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str
    data_type: Literal["grades", "schedule", "requirements"]
    confirmed_at: datetime
    result: dict
    note: str


class DataRow(BaseModel):
    data_type: Literal["grades", "schedule", "requirements"]
    academic_year: str | None = None
    semester: int | None = None
    records: int | None = None
    snapshot_id: int | None = None
    source_file: str | None = None
    imported_at: datetime


class DataStatus(BaseModel):
    items: list[DataRow]
    note: str


class RequirementTreeNode(DegreeProgressNode):
    expected_course_count: int | None = Field(default=None, ge=0)
    passed_course_count: int | None = Field(default=None, ge=0)
    courses: list[RequirementCourseInput] = Field(default_factory=list)
    children: list["RequirementTreeNode"] = Field(default_factory=list)


class RequirementTree(service.DegreeProgressResult):
    tree: list[RequirementTreeNode]


class TaskRow(BaseModel):
    task_id: str
    data_type: Literal["grades", "schedule", "requirements"]
    status: Literal["started", "validated", "failed", "cancelled"]
    academic_year: str | None = None
    semester: int | None = None
    started_at: datetime | None = None
    recorded_at: datetime | None = None
    stage: str | None = None
    raw_file: str | None = None
    raw_sha256: str | None = None
    parsed_counts: dict[str, int] | None = None
    error_type: str | None = None


class TaskStatus(BaseModel):
    items: list[TaskRow]
    malformed_lines: int = 0
    note: str


def check_origin(request):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, detail={"code": "ORIGIN_REJECTED", "message": "只允许同源页面执行导入操作"})


def guarded(function, *args):
    try:
        return function(*args)
    except service.ManagementError as error:
        raise HTTPException(error.status, detail={"code": error.code, "message": error.message}) from None
    except SQLAlchemyError:
        raise HTTPException(503, detail={"code": "DATABASE_ERROR", "message": "数据库操作失败，请检查连接；导入事务未成功时不会替换旧数据。"}) from None
    except Exception:
        raise HTTPException(500, detail={"code": "MANAGEMENT_ERROR", "message": "数据操作失败，请检查本地文件和数据库状态；未确认成功前不要视为已更新。"}) from None


@router.post("/imports/preview", response_model=service.Preview)
async def preview_upload(request: Request, data_type: Literal["grades", "schedule", "requirements"]):
    check_origin(request)
    filename = unquote(request.headers.get("x-file-name", ""))
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > service.MAX_BYTES:
            raise HTTPException(413, detail={"code": "FILE_SIZE", "message": "文件不得超过10MB"})
    return await run_in_threadpool(guarded, service.create_preview, data_type, filename, bytes(content))


@router.post("/imports/{preview_id}/confirm", response_model=ImportResult)
def confirm_import(preview_id: str, request: Request):
    check_origin(request)
    return guarded(service.confirm_preview, preview_id)


@router.get("/data/status", response_model=DataStatus)
def status():
    return guarded(service.data_status)


@router.get("/data/requirements", response_model=RequirementTree)
def requirements():
    return guarded(service.current_requirements)


@router.get("/collections/tasks", response_model=TaskStatus)
def tasks(limit: int = Query(default=50, ge=1, le=100)):
    return guarded(service.collection_tasks, limit)
