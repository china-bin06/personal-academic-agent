import asyncio
import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.services import academic_calendar as calendar
from app.tools import calendar_schedule, runner
from app.schemas.tool_params import DateScheduleParams
from app.schemas.tool_results import DateScheduleResult
from app.agent import service as agent


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(calendar, "STORE_PATH", tmp_path / "calendar.sqlite3")
    monkeypatch.setattr(calendar, "current_time", lambda: datetime(2026, 9, 24, 23, 30, tzinfo=calendar.SHANGHAI))
    monkeypatch.setattr(runner, "write_audit", lambda record: None)
    return TestClient(app)


def config(**changes):
    return {"academic_year": "2026-2027", "semester": 1, "first_monday": "2026-09-07", "teaching_weeks": 20, **changes}


@pytest.mark.parametrize("changes", [
    {"first_monday": "2026-09-08"}, {"academic_year": "2026-2028"},
    {"first_monday": "2025-09-08"}, {"teaching_weeks": 0}, {"teaching_weeks": 61},
    {"semester": 8}, {"semester": "1"}, {"command": "anything"},
])
def test_invalid_calendar_is_not_saved(isolated, changes):
    assert isolated.put("/api/v1/calendar", json=config(**changes)).status_code == 422
    assert calendar.load_config() is None


def test_save_read_and_owner_scope(isolated):
    assert isolated.get("/api/v1/calendar").json()["configuration"] is None
    assert isolated.put("/api/v1/calendar", json=config(), headers={"Origin": "https://other.example"}).status_code == 403
    response = isolated.put("/api/v1/calendar", json=config())
    assert response.status_code == 200
    assert response.json()["timezone"] == "Asia/Shanghai"
    assert isolated.get("/api/v1/calendar").json()["configuration"]["first_monday"] == "2026-09-07"
    assert calendar.load_config("other") is None


def test_missing_calendar_and_out_of_term_do_not_query(isolated, monkeypatch):
    def rejected(*args): raise AssertionError("不应查询未解析日期")
    monkeypatch.setattr(calendar_schedule, "get_schedule", rejected)
    result = calendar_schedule.get_schedule_for_date(None, DateScheduleParams(relative_day="明天"), "local")
    assert DateScheduleResult.model_validate(result).resolution_status == "needs_configuration"
    calendar.save_config(calendar.CalendarInput(**config()))
    for value in ["2026-09-06", "2027-01-25"]:
        result = calendar_schedule.get_schedule_for_date(None, DateScheduleParams(target_date=value), "local")
        assert result["resolution_status"] == "out_of_term"
        assert result.get("week") is None


def test_date_week_mapping_and_timezone_year_boundary(isolated, monkeypatch):
    calendar.save_config(calendar.CalendarInput(**config()))
    seen = []
    def query(session, params, owner):
        seen.append(params)
        return {"snapshot_id": 1, "items": [], "unscheduled_courses": [], "note": "按常规课表查询"}
    monkeypatch.setattr(calendar_schedule, "get_schedule", query)
    tomorrow = calendar_schedule.get_schedule_for_date(None, DateScheduleParams(relative_day="明天"), "local")
    assert (tomorrow["target_date"], tomorrow["week"], tomorrow["weekday"]) == (date(2026, 9, 25), 3, 5)
    fourth = calendar_schedule.get_schedule_for_date(None, DateScheduleParams(target_date="2026-10-02"), "local")
    assert fourth["week"] == 4 and seen[-1].weekday == 5
    # UTC 12月31日晚，在北京时间已经是1月1日；明天应为1月2日。
    monkeypatch.setattr(calendar, "current_time", lambda: datetime(2026, 12, 31, 18, 30, tzinfo=timezone.utc).astimezone(calendar.SHANGHAI))
    boundary = calendar_schedule.get_schedule_for_date(None, DateScheduleParams(relative_day="明天"), "local")
    assert (boundary["target_date"], boundary["week"], boundary["weekday"]) == (date(2027, 1, 2), 17, 6)


@pytest.mark.parametrize("params", [{}, {"relative_day": "昨天"}, {"target_date": "2026-09-25", "relative_day": "明天"}, {"target_date": "bad"}, {"relative_day": "明天", "sql": "DELETE"}])
def test_date_tool_parameter_contract(params):
    with pytest.raises(ValidationError): DateScheduleParams.model_validate(params)


def test_registered_tool_without_config_returns_explainable_result(isolated):
    result = runner.run_tool("get_schedule_for_date", {"relative_day": "明天"}, owner_id="local")
    assert result["status"] == "success"
    assert result["data"]["resolution_status"] == "needs_configuration"
    assert result["data"]["target_date"] == "2026-09-25"


class Call:
    type = "function"
    def __init__(self, name, arguments):
        self.id = name
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments))
    def model_dump(self, **kwargs):
        return {"id": self.id, "type": self.type, "function": vars(self.function)}


@pytest.mark.parametrize("resolved", [True, False])
def test_agent_routes_relative_day_and_requires_clarification_when_unresolved(isolated, monkeypatch, resolved):
    seen = []
    def tool(name, arguments, owner_id):
        assert name == "get_schedule_for_date" and arguments == {"relative_day": "明天"}
        return {"status": "success", "request_id": "date-evidence", "data": {"resolution_status": "resolved" if resolved else "needs_configuration"}}
    monkeypatch.setattr(agent, "run_tool", tool)
    calls = [Call("get_schedule_for_date", {"relative_day": "明天"}),
             Call("finish_answer", {"status": "answered", "answer": "日期查询结果", "evidence_ids": ["date-evidence"]})]
    if not resolved:
        calls.append(Call("finish_answer", {"status": "needs_clarification", "answer": "请同步开学日期", "evidence_ids": ["date-evidence"]}))
    async def create(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[calls.pop(0)]))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    response = asyncio.run(agent.agent_loop("明天有什么课？", "local", client, []))
    assert response.status == ("answered" if resolved else "needs_clarification")
    assert response.evidence[0].arguments == {"relative_day": "明天"}
    assert "get_schedule_for_date" in [item["function"]["name"] for item in seen[0]["tools"]]
