"""本地单用户的数据预览、确认导入和状态读取。"""
import hashlib
import json
import re
import sqlite3
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import ZipFile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.read_session import read_engine
from app.importers.grades_excel import parse_grades_excel
from app.importers.requirements_html import parse_requirements_html
from app.models.grade import Grade
from app.models.requirement import RequirementSnapshot, RequirementNode
from app.models.schedule import ScheduleSnapshot
from app.schemas.grade import GradeInput
from app.schemas.requirement import RequirementNodeInput, RequirementCourseInput
from app.schemas.schedule import ScheduleInput
from app.schemas.tool_params import DegreeProgressParams
from app.schemas.tool_results import DegreeProgressResult
from app.tools.requirements import get_degree_progress

ROOT = Path(__file__).resolve().parents[2]
STORE_PATH = ROOT / "data" / "previews" / "previews.sqlite3"
MAX_BYTES = 10 * 1024 * 1024
TTL_SECONDS = 30 * 60
SUFFIXES = {"grades": {".xlsx"}, "requirements": {".html", ".htm"},
            "schedule": {".json", ".pdf"}}


class ManagementError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class Preview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    data_type: Literal["grades", "schedule", "requirements"]
    filename: str
    sha256: str
    expires_at: datetime
    summary: dict
    payload: dict | list
    warnings: list[str] = Field(default_factory=list)


def _store():
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(STORE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE IF NOT EXISTS previews (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL,
        preview TEXT NOT NULL, raw BLOB NOT NULL, result TEXT
    )""")
    connection.commit()
    return connection


def safe_filename(filename):
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^\w.()\-\u4e00-\u9fff]", "_", name)[:160]
    if not name or name.startswith("."):
        raise ManagementError("INVALID_FILENAME", "文件名无效")
    return name


def requirement_tree(nodes):
    """接收已校验的平面节点，拒绝缺失父节点和环，不累计父子学分。"""
    entries, parents = {}, {}
    for node in nodes:
        key = node.get("node_id", node.get("source_node_id"))
        parent = node.get("parent_id", node.get("parent_source_id"))
        if not key or key in entries:
            raise ManagementError("INVALID_TREE", "培养计划节点标识缺失或重复")
        entry = dict(node)
        entry["children"] = []
        entries[key], parents[key] = entry, parent
    if len(entries) > 500:
        raise ManagementError("INVALID_TREE", "培养计划节点超过500个")
    for key in entries:
        visited, current = set(), key
        while current is not None:
            if current in visited or current not in entries:
                raise ManagementError("INVALID_TREE", "培养计划父子关系不完整或存在环")
            visited.add(current)
            if len(visited) > 50:
                raise ManagementError("INVALID_TREE", "培养计划层级超过50层")
            current = parents[current]
    roots = []
    for key, entry in entries.items():
        parent = parents[key]
        (roots if parent is None else entries[parent]["children"]).append(entry)
    return roots


def parse_upload(kind, filename, raw):
    if kind not in SUFFIXES or Path(filename).suffix.lower() not in SUFFIXES[kind]:
        raise ManagementError("UNSUPPORTED_FORMAT", "该数据类型不支持此文件格式")
    if not raw or len(raw) > MAX_BYTES:
        raise ManagementError("FILE_SIZE", "文件不能为空，且不得超过10MB", 413)
    with TemporaryDirectory() as directory:
        path = Path(directory) / filename
        path.write_bytes(raw)
        if kind == "grades":
            # 限制压缩包展开体积，避免小文件包含极大的工作表。
            with ZipFile(path) as archive:
                if sum(x.file_size for x in archive.infolist()) > 40 * 1024 * 1024:
                    raise ManagementError("FILE_SIZE", "Excel解压后体积超过40MB", 413)
            records, errors = parse_grades_excel(path)
            if errors:
                rows = ", ".join(str(x["row"]) for x in errors[:10])
                raise ManagementError("INVALID_ROWS", f"成绩校验失败，请检查行号：{rows}")
            if not records or len(records) > 5000:
                raise ManagementError("INVALID_ROWS", "成绩记录为空或超过5000条")
            if len({x.student_id for x in records}) != 1:
                raise ManagementError("MULTIPLE_STUDENTS", "仅允许单个学生的成绩文件")
            payload = [x.model_dump(mode="json") for x in records]
            summary = {"records": len(records), "terms": sorted({
                f"{x.academic_year}-{x.semester}" for x in records})}
            warnings = ["保留原始考试性质；问答统计仍沿用现有百分制口径。"]
        elif kind == "requirements":
            nodes = parse_requirements_html(raw.decode("utf-8-sig"))
            payload = [x.model_dump(mode="json") for x in nodes]
            requirement_tree(payload)
            summary = {"nodes": len(nodes), "course_entries": sum(len(x.courses) for x in nodes)}
            warnings = ["父子类别分别展示，不能重复累计学分；学分差值不等于满足全部毕业条件。"]
        else:
            if path.suffix.lower() == ".pdf":
                from scripts.extract_schedule_blocks import extract_blocks
                from scripts.normalize_schedule_blocks import parse_other, parse_scheduled
                from scripts.build_schedule_candidate import build_candidate, read_json
                blocks = extract_blocks(path)
                normalized = {k: blocks[k] for k in ("source_file", "academic_year", "semester")}
                normalized["scheduled_records"] = []
                for i, block in enumerate(blocks["scheduled_blocks"], 1):
                    try:
                        normalized["scheduled_records"].append(parse_scheduled(block))
                    except (ValueError, KeyError, TypeError):
                        raise ManagementError("PDF_BLOCK", f"第{i}个课程块无法解析，页码{block['source_pages']}，星期{block['weekday']}") from None
                normalized["other_courses"] = [parse_other(x) for x in blocks["other_courses"]]
                reference_path = ROOT / "data" / "candidates" / (
                    f"schedule-{blocks['academic_year']}-{blocks['semester']}.json")
                if not reference_path.is_file():
                    raise ManagementError("REFERENCE_REQUIRED", "该学期PDF缺少已确认参考课表。请先准备参考JSON，或上传完整结构化课表JSON。")
                reference = ScheduleInput.model_validate(read_json(reference_path))
                data = build_candidate(normalized, reference, reference_path)
                warnings = ["PDF课程标识和未排课课程学分引用已确认的参考JSON，请核对预览。"]
            else:
                data = ScheduleInput.model_validate_json(raw)
                warnings = []
            if len(data.courses) > 200 or sum(len(x.meetings) for x in data.courses) > 500:
                raise ManagementError("TOO_MANY_RECORDS", "课表超过200门课程或500条上课安排")
            payload = data.model_dump(mode="json")
            summary = {"academic_year": data.academic_year, "semester": data.semester,
                       "courses": len(data.courses), "meetings": sum(len(x.meetings) for x in data.courses),
                       "unscheduled_courses": sum(not x.meetings for x in data.courses)}
    return payload, summary, warnings


def create_preview(kind, filename, raw, owner="local"):
    filename = safe_filename(filename)
    try:
        payload, summary, warnings = parse_upload(kind, filename, raw)
    except ManagementError:
        raise
    except Exception:
        raise ManagementError("PARSE_FAILED", "文件解析失败，请检查格式、字段和页面完整性；未写入学业数据库。") from None
    expires = datetime.now(timezone.utc) + timedelta(seconds=TTL_SECONDS)
    preview = Preview(preview_id=uuid4().hex, data_type=kind, filename=filename,
                      sha256=hashlib.sha256(raw).hexdigest(), expires_at=expires,
                      summary=summary, payload=payload, warnings=warnings)
    connection = _store()
    try:
        with connection:
            connection.execute("DELETE FROM previews WHERE expires < ?", (datetime.now(timezone.utc).timestamp(),))
            connection.execute("INSERT INTO previews VALUES (?, ?, ?, ?, ?, NULL)",
                               (preview.preview_id, owner, expires.timestamp(), preview.model_dump_json(), raw))
    finally:
        connection.close()
    return preview


def perform_import(preview, raw, path, owner):
    if hashlib.sha256(raw).hexdigest() != preview.sha256:
        raise ManagementError("FILE_CHANGED", "暂存文件校验失败，请重新上传")
    if preview.data_type == "grades":
        from app.services.grade_import import import_grades
        return import_grades([GradeInput.model_validate(x) for x in preview.payload], path, preview.sha256, owner)
    if preview.data_type == "requirements":
        from app.services.requirement_import import import_requirement_snapshot
        return import_requirement_snapshot([RequirementNodeInput.model_validate(x) for x in preview.payload], path, preview.sha256, owner)
    from app.services.schedule_import import import_schedule_snapshot
    return import_schedule_snapshot(ScheduleInput.model_validate(preview.payload), path, preview.sha256, owner)


def confirm_preview(preview_id, owner="local"):
    if not re.fullmatch(r"[0-9a-f]{32}", preview_id):
        raise ManagementError("PREVIEW_NOT_FOUND", "预览不存在", 404)
    connection = _store()
    try:
        # 跨进程串行确认，避免双击或并发请求重复执行同一预览。
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM previews WHERE id=? AND owner=?", (preview_id, owner)).fetchone()
        if row is None:
            raise ManagementError("PREVIEW_NOT_FOUND", "预览不存在或已清理", 404)
        if row["expires"] < datetime.now(timezone.utc).timestamp():
            raise ManagementError("PREVIEW_EXPIRED", "预览已过期，请重新上传", 410)
        if row["result"]:
            return json.loads(row["result"])
        preview = Preview.model_validate_json(row["preview"])
        path = ROOT / "data" / "uploads" / preview_id / preview.filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(row["raw"])
        imported = perform_import(preview, row["raw"], path, owner)
        result = {"preview_id": preview_id, "data_type": preview.data_type,
                  "confirmed_at": datetime.now(timezone.utc).isoformat(), "result": imported,
                  "note": "导入已完成；相同内容未变化时，数据库数据时间保持不变。"}
        connection.execute("UPDATE previews SET result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), preview_id))
        connection.commit()
        return result
    finally:
        connection.rollback()
        connection.close()


def data_status(owner="local"):
    with Session(read_engine) as session:
        grades = session.execute(select(Grade.academic_year, Grade.semester,
            func.count(Grade.id), func.max(Grade.imported_at)).where(Grade.owner_id == owner)
            .group_by(Grade.academic_year, Grade.semester).order_by(Grade.academic_year.desc(), Grade.semester.desc())).all()
        schedules = session.scalars(select(ScheduleSnapshot).where(ScheduleSnapshot.owner_id == owner)
            .order_by(ScheduleSnapshot.imported_at.desc(), ScheduleSnapshot.id.desc()).limit(200)).all()
        requirements = session.scalar(select(RequirementSnapshot).where(RequirementSnapshot.owner_id == owner)
            .order_by(RequirementSnapshot.imported_at.desc(), RequirementSnapshot.id.desc()).limit(1))
        rows = [{"data_type": "grades", "academic_year": year, "semester": sem,
                 "records": count, "imported_at": time} for year, sem, count, time in grades]
        seen = set()
        for snapshot in schedules:
            key = (snapshot.academic_year, snapshot.semester)
            if key not in seen:
                seen.add(key)
                rows.append({"data_type": "schedule", "academic_year": key[0], "semester": key[1],
                             "snapshot_id": snapshot.id, "source_file": snapshot.source_file, "imported_at": snapshot.imported_at})
        if requirements:
            rows.append({"data_type": "requirements", "snapshot_id": requirements.id,
                         "source_file": requirements.source_file, "imported_at": requirements.imported_at})
        return {"items": rows, "note": "时间来自数据库；成绩是各学期记录最后写入时间，快照是导入时间，不代表网页最新发布时间。"}


def current_requirements(owner="local"):
    with Session(read_engine) as session:
        result = DegreeProgressResult.model_validate(get_degree_progress(session, DegreeProgressParams(), owner)).model_dump(mode="json")
        # 展示页补充同一快照的课程明细，不扩大问答工具的输出。
        detailed = []
        if result["snapshot_id"] is not None:
            rows = session.scalars(select(RequirementNode).where(RequirementNode.snapshot_id == result["snapshot_id"])
                .order_by(RequirementNode.id).limit(501)).all()
            by_id = {row.source_node_id: row for row in rows}
            for node in result["nodes"]:
                row = by_id.get(node["node_id"])
                if row is None:
                    raise ManagementError("INVALID_TREE", "培养计划快照明细不完整")
                detailed.append({**node, "expected_course_count": row.expected_course_count,
                    "passed_course_count": row.passed_course_count,
                    "courses": [RequirementCourseInput.model_validate(course).model_dump(mode="json") for course in row.courses]})
    result["tree"] = requirement_tree(detailed)
    return result


def collection_tasks(limit=50):
    path = ROOT / "logs" / "collections.jsonl"
    if not path.is_file():
        return {"items": [], "note": "尚无采集日志。"}
    with path.open(encoding="utf-8") as file:
        lines = deque(file, maxlen=2000)
    tasks, malformed = {}, 0
    allowed = {"task_id", "data_type", "academic_year", "semester", "started_at", "recorded_at",
               "status", "stage", "raw_file", "raw_sha256", "parsed_counts", "error_type"}
    for line in lines:
        try:
            record = json.loads(line)
            if not isinstance(record, dict) or not re.fullmatch(r"[0-9a-f]{32}", record.get("task_id", "")):
                raise ValueError()
            record = {k: v for k, v in record.items() if k in allowed}
            raw_file = record.get("raw_file")
            if raw_file:
                candidate = ROOT / raw_file
                record["raw_file"] = candidate.resolve().relative_to(ROOT).as_posix()
            tasks[record["task_id"]] = record
        except (ValueError, TypeError, OSError):
            malformed += 1
    return {"items": list(reversed(list(tasks.values())))[:limit], "malformed_lines": malformed,
            "note": "展示最近2000行日志中的任务。started仅表示已开始且尚未见结束记录，不能证明进程仍在运行；此页不启动采集。"}
