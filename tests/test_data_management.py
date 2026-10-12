import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.main import app
from app.models.grade import Grade
from app.services import data_management as service
from app.services import grade_import


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "ROOT", tmp_path)
    monkeypatch.setattr(service, "STORE_PATH", tmp_path / "previews.sqlite3")
    engine = create_engine(f"sqlite:///{tmp_path / 'grades.sqlite3'}")
    Grade.__table__.create(engine)
    monkeypatch.setattr(grade_import, "engine", engine)
    yield tmp_path, engine
    engine.dispose()


@pytest.fixture
def client(isolated):
    with TestClient(app) as client:
        yield client


def grade_bytes(score=80):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "sheet1"
    sheet.append(["学号", "学年", "学期", "课程代码", "课程名称", "课程性质",
                  "课程类别", "学分", "成绩", "成绩性质", "是否成绩作废", "教学班"])
    sheet.append(["test-student", "2025-2026", "1", "TEST01", "测试课程",
                  "必修课", "专业课", "2", score, "正常考试", "否", "测试班"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def schedule_bytes(weekday=5):
    return json.dumps({"academic_year": "2026-2027", "semester": 1,
        "source_note": "虚构测试", "courses": [
            {"course_key": "robot", "course_code": "TEST01", "course_name": "机器人测试课",
             "credits": "2", "meetings": [{"teaching_type": "理论", "weekday": weekday,
                 "period_start": 5, "period_end": 6, "weeks": [1, 3, 5], "location": "测试教室"}]},
            {"course_key": "project", "course_name": "未排课项目", "credits": "1", "meetings": []}
        ]}, ensure_ascii=False).encode()


def upload(client, kind, filename, raw):
    return client.post(f"/api/v1/imports/preview?data_type={kind}", content=raw,
                       headers={"X-File-Name": filename, "Content-Type": "application/octet-stream"})


def test_preview_does_not_write_academic_database(client, isolated):
    response = upload(client, "grades", "grades.xlsx", grade_bytes())
    assert response.status_code == 200
    assert response.json()["summary"]["records"] == 1
    with Session(isolated[1]) as session:
        assert session.scalar(select(func.count()).select_from(Grade)) == 0


def test_confirm_and_duplicate_confirmation(client, isolated):
    raw = grade_bytes()
    preview = upload(client, "grades", "grades.xlsx", raw).json()
    url = f"/api/v1/imports/{preview['preview_id']}/confirm"
    first, second = client.post(url), client.post(url)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["result"]["inserted"] == 1
    # 新预览上传完全相同文件，也由原导入服务去重。
    again = upload(client, "grades", "grades.xlsx", raw).json()
    result = client.post(f"/api/v1/imports/{again['preview_id']}/confirm").json()
    assert result["result"] == {"inserted": 0, "updated": 0, "unchanged": 1}
    with Session(isolated[1]) as session:
        assert session.scalar(select(func.count()).select_from(Grade)) == 1


def test_updated_grade_uses_existing_service(client, isolated):
    for score in (80, 90):
        preview = upload(client, "grades", "grades.xlsx", grade_bytes(score)).json()
        result = client.post(f"/api/v1/imports/{preview['preview_id']}/confirm")
        assert result.status_code == 200
    assert result.json()["result"]["updated"] == 1
    with Session(isolated[1]) as session:
        assert session.scalar(select(Grade.score_percent)) == 90


def test_failed_import_keeps_old_data_and_allows_retry(client, isolated, monkeypatch):
    preview = upload(client, "grades", "grades.xlsx", grade_bytes()).json()
    client.post(f"/api/v1/imports/{preview['preview_id']}/confirm")
    changed = upload(client, "grades", "grades.xlsx", grade_bytes(90)).json()
    original = service.perform_import
    def broken(*args):
        raise OperationalError(None, None, Exception("private-secret"))
    monkeypatch.setattr(service, "perform_import", broken)
    failed = client.post(f"/api/v1/imports/{changed['preview_id']}/confirm")
    assert failed.status_code == 503
    assert "private-secret" not in failed.text
    with Session(isolated[1]) as session:
        assert session.scalar(select(Grade.score_percent)) == 80
    monkeypatch.setattr(service, "perform_import", original)
    assert client.post(f"/api/v1/imports/{changed['preview_id']}/confirm").status_code == 200


def test_expired_missing_and_owner_scoped_previews(client):
    preview = upload(client, "grades", "grades.xlsx", grade_bytes()).json()
    connection = service._store()
    with connection:
        connection.execute("UPDATE previews SET expires=0 WHERE id=?", (preview["preview_id"],))
    connection.close()
    assert client.post(f"/api/v1/imports/{preview['preview_id']}/confirm").status_code == 410
    assert client.post("/api/v1/imports/missing/confirm").status_code == 404
    other = service.create_preview("grades", "grades.xlsx", grade_bytes(), owner="other")
    assert client.post(f"/api/v1/imports/{other.preview_id}/confirm").status_code == 404


def test_parallel_confirm_executes_import_once(isolated, monkeypatch):
    preview = service.create_preview("grades", "grades.xlsx", grade_bytes())
    calls = []
    def fake(*args):
        calls.append(1)
        return {"inserted": 1, "updated": 0, "unchanged": 0}
    monkeypatch.setattr(service, "perform_import", fake)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(service.confirm_preview, [preview.preview_id] * 2))
    assert results[0] == results[1]
    assert len(calls) == 1


@pytest.mark.parametrize("kind,name,raw", [
    ("grades", "wrong.pdf", b"x"), ("grades", "broken.xlsx", b"not-an-excel"),
    ("requirements", "login.html", b"<html>login</html>"),
    ("schedule", "invalid.json", schedule_bytes(8)), ("schedule", "empty.json", b""),
])
def test_invalid_uploads_cannot_be_confirmed(client, kind, name, raw):
    response = upload(client, kind, name, raw)
    assert response.status_code in (400, 413)
    assert "preview_id" not in response.json()


def test_upload_limit_and_cross_origin(client, monkeypatch):
    monkeypatch.setattr(service, "MAX_BYTES", 16)
    assert upload(client, "grades", "grades.xlsx", b"x" * 17).status_code == 413
    response = client.post("/api/v1/imports/preview?data_type=grades", content=b"x",
                           headers={"Origin": "https://other.example", "X-File-Name": "grades.xlsx"})
    assert response.status_code == 403


def test_schedule_preview_and_safe_filename(client):
    response = upload(client, "schedule", "../../schedule.json", schedule_bytes())
    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "schedule.json"
    assert data["summary"] == {"academic_year": "2026-2027", "semester": 1,
                               "courses": 2, "meetings": 1, "unscheduled_courses": 1}
    assert data["payload"]["courses"][0]["meetings"][0]["weeks"] == [1, 3, 5]


def test_requirement_tree_and_invalid_relations():
    nodes = [{"node_id": "root", "parent_id": None, "name": "主修"},
             {"node_id": "child", "parent_id": "root", "name": "必修"}]
    tree = service.requirement_tree(nodes)
    assert tree[0]["children"][0]["name"] == "必修"
    for bad in ([nodes[1]], [nodes[0], nodes[0]],
                [{"node_id": "x", "parent_id": "x"}]):
        with pytest.raises(service.ManagementError):
            service.requirement_tree(bad)


def test_tasks_merge_redact_and_tolerate_damaged_lines(client, isolated):
    directory = isolated[0] / "logs"
    directory.mkdir()
    task = {"task_id": "a" * 32, "data_type": "schedule", "status": "started"}
    end = {**task, "status": "failed", "error_type": "TimeoutError", "Cookie": "secret"}
    (directory / "collections.jsonl").write_text(
        json.dumps(task) + "\n" + "{broken\n" + json.dumps(end) + "\n", encoding="utf-8")
    response = client.get("/api/v1/collections/tasks")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["status"] == "failed"
    assert response.json()["malformed_lines"] == 1
    assert "secret" not in response.text


def test_database_read_failure_is_not_empty_success(client, monkeypatch):
    def broken():
        raise OperationalError(None, None, Exception("private-secret"))
    monkeypatch.setattr(service, "data_status", broken)
    response = client.get("/api/v1/data/status")
    assert response.status_code == 503
    assert "private-secret" not in response.text


def test_home_resources_and_existing_chat_route(client):
    for path in ("/", "/static/app.js", "/static/management.js", "/static/styles.css"):
        assert client.get(path).status_code == 200
    schema = client.get("/openapi.json").json()
    assert "/api/v1/chat" in schema["paths"]
    assert schema["info"]["version"] == "0.2.0"
