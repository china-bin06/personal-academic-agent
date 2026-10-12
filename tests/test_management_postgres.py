"""设置 RUN_POSTGRES_TESTS=1 后执行；创建并清理独立测试 schema。"""
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.schema import CreateSchema, DropSchema
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import engine as original_engine
from app.models.schedule import ScheduleSnapshot
from app.services import data_management as service
from app.services import grade_import, requirement_import, schedule_import
from test_data_management import grade_bytes, schedule_bytes
from app.importers.requirements_html import EXPECTED_HEADERS


@pytest.fixture
def postgres(tmp_path, monkeypatch):
    if os.environ.get("RUN_POSTGRES_TESTS") != "1":
        pytest.skip("需要 RUN_POSTGRES_TESTS=1 和本地 PostgreSQL")
    schema = "agent_v2_test_" + uuid4().hex
    with original_engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    engine = original_engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(engine)
        monkeypatch.setattr(service, "ROOT", tmp_path)
        monkeypatch.setattr(service, "STORE_PATH", tmp_path / "previews.sqlite3")
        monkeypatch.setattr(service, "read_engine", engine)
        from app.services import academic_calendar
        monkeypatch.setattr(academic_calendar, "STORE_PATH", tmp_path / "calendar.sqlite3")
        for module in (grade_import, requirement_import, schedule_import):
            monkeypatch.setattr(module, "engine", engine)
        yield engine
    finally:
        assert schema.startswith("agent_v2_test_") and len(schema) == 46
        with original_engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))


def plan_html():
    headers = "".join(f"<th>{x}</th>" for x in EXPECTED_HEADERS)
    cells = ["已修", "2025-2026", "1", "TEST01", "", "测试课程", "理论(2)", "必修课",
             "2", "专业课", "80", "3", "80", "", "", "2025-2026", "1", "1"]
    row = "".join(f"<td>{x}</td>" for x in cells)
    return f'''<ul><li xfyqjd_id="root"><div class="title" xfyqjd_id="root"><p class="title1" yqzdxf="4" yxxf="2">主修</p></div>
    <ul><li xfyqjd_id="child" fxfyqjd_id="root"><div class="title" xfyqjd_id="child" sfmjd="1"><p class="title1" yqzdxf="4" yxxf="2">必修 要求学分:4<span><font name="zms">1</font><font name="yxmc">1</font></span></p></div>
    <div id="kcxxchild"><table><thead><tr>{headers}</tr></thead><tbody><tr kch_id="course">{row}</tr></tbody></table></div></li></ul></li></ul>'''.encode()


def test_postgres_all_imports_status_tree_dedup_and_rollback(postgres, monkeypatch):
    for kind, name, raw in (("grades", "grades.xlsx", grade_bytes()),
                            ("requirements", "plan.html", plan_html()),
                            ("schedule", "schedule.json", schedule_bytes())):
        preview = service.create_preview(kind, name, raw)
        result = service.confirm_preview(preview.preview_id)
        assert result["data_type"] == kind
        again = service.create_preview(kind, name, raw)
        duplicate = service.confirm_preview(again.preview_id)["result"]
        if kind == "grades":
            assert duplicate == {"inserted": 0, "updated": 0, "unchanged": 1}
        else:
            assert duplicate["status"] == "unchanged"
    status = service.data_status()
    assert len(status["items"]) == 3
    assert all(x["imported_at"] is not None for x in status["items"])
    tree = service.current_requirements()
    assert tree["tree"][0]["children"][0]["name"] == "必修"
    assert tree["tree"][0]["children"][0]["credit_shortfall"] == "2.000"
    child = tree["tree"][0]["children"][0]
    assert child["courses"][0]["course_code"] == "TEST01"
    assert child["courses"][0]["study_status"] == "已修"
    assert child["expected_course_count"] == child["passed_course_count"] == 1
    assert all("courses" not in node for node in tree["nodes"])  # 问答摘要口径不扩大。
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        response = client.get("/api/v1/data/requirements")
        assert response.status_code == 200
        assert response.json()["tree"][0]["children"][0]["courses"][0]["credits"] == "2"
    foreign = service.create_preview("requirements", "foreign.html", plan_html().replace(b"TEST01", b"FOREIGN"), owner="other")
    service.confirm_preview(foreign.preview_id, owner="other")
    assert service.current_requirements()["tree"][0]["children"][0]["courses"][0]["course_code"] == "TEST01"
    newer = service.create_preview("requirements", "newer.html", plan_html().replace(b"TEST01", b"TEST02"))
    new_result = service.confirm_preview(newer.preview_id)
    latest = service.current_requirements()
    assert latest["snapshot_id"] == new_result["result"]["snapshot_id"]
    assert latest["tree"][0]["children"][0]["courses"][0]["course_code"] == "TEST02"
    changed = json.loads(schedule_bytes())
    changed["source_note"] = "失败事务测试"
    preview = service.create_preview("schedule", "schedule.json", json.dumps(changed).encode())
    def fail(*args, **kwargs):
        raise RuntimeError("simulated-write-failure")
    with monkeypatch.context() as patch:
        patch.setattr(schedule_import, "ScheduleMeeting", fail)
        with pytest.raises(RuntimeError):
            service.confirm_preview(preview.preview_id)
    with Session(postgres) as session:
        assert session.scalar(select(func.count()).select_from(ScheduleSnapshot)) == 1
    assert service.confirm_preview(preview.preview_id)["result"]["status"] == "created"
    from app.services import academic_calendar
    from app.schemas.tool_params import DateScheduleParams
    from app.tools.calendar_schedule import get_schedule_for_date
    academic_calendar.save_config(academic_calendar.CalendarInput(academic_year="2026-2027", semester=1,
        first_monday="2026-09-07", teaching_weeks=20))
    with Session(postgres) as session:
        odd = get_schedule_for_date(session, DateScheduleParams(target_date="2026-09-25"), "local")
        even = get_schedule_for_date(session, DateScheduleParams(target_date="2026-10-02"), "local")
        assert odd["week"] == 3 and odd["items"][0]["course_name"] == "机器人测试课"
        assert even["week"] == 4 and even["items"] == []
