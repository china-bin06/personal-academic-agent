"""隔离任务状态与浏览器替身；不访问学校、不启动真实采集、不写个人数据。"""
import json
import time
from types import SimpleNamespace
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import collection_control as control
from app.services import data_management as management
from scripts import collect_from_page as worker


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "ROOT", tmp_path)
    monkeypatch.setattr(control, "STORE_PATH", tmp_path / "tasks.sqlite3")
    monkeypatch.setattr(management, "ROOT", tmp_path)
    monkeypatch.setattr(management, "STORE_PATH", tmp_path / "previews.sqlite3")
    calls = []
    monkeypatch.setattr(control.subprocess, "Popen", lambda command, **options: calls.append((command, options)) or object())
    monkeypatch.setattr(control, "monitor", lambda *args: None)
    return TestClient(app), calls, tmp_path


def start(client, **payload):
    return client.post("/api/v1/collections/jobs", json={"data_type": "schedule", "academic_year": "2026-2027", "semester": 1, **payload})


@pytest.mark.parametrize("payload", [
    {"data_type": "other"}, {"data_type": "grades"},
    {"data_type": "schedule", "academic_year": "2026-2028", "semester": 1},
    {"data_type": "schedule", "academic_year": "2026-2027", "semester": 8},
    {"data_type": "grades", "academic_year": "2026-2027", "semester": "1"},
    {"data_type": "requirements", "academic_year": "2026-2027"},
    {"data_type": "requirements", "command": "anything"},
])
def test_invalid_requests_never_spawn(sandbox, payload):
    client, calls, _ = sandbox
    assert client.post("/api/v1/collections/jobs", json=payload).status_code == 422
    assert calls == []


def test_fixed_worker_singleton_and_origins(sandbox):
    client, calls, _ = sandbox
    assert start(client).status_code == 202
    assert len(calls) == 1
    command, options = calls[0]
    assert command[1:4] == ["-m", "scripts.collect_from_page", "--task-id"]
    assert options["shell"] is False
    assert start(client).status_code == 409
    task_id = client.get("/api/v1/collections/jobs").json()[0]["task_id"]
    assert client.post(f"/api/v1/collections/jobs/{task_id}/cancel", headers={"Origin": "https://other.example"}).status_code == 403
    assert client.post("/api/v1/collections/jobs", json={"data_type": "requirements"}, headers={"Origin": "https://other.example"}).status_code == 403
    assert client.get("/api/v1/collections/jobs/not-an-id").status_code == 404


def test_concurrent_start_one_worker(sandbox):
    _, calls, _ = sandbox
    params = control.CollectionRequest(data_type="requirements")
    def attempt():
        try:
            return control.start_task(params)["task_id"]
        except management.ManagementError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(lambda _: attempt(), range(2)))
    assert result.count("TASK_BUSY") == 1
    assert len(calls) == 1


def test_continue_cancel_and_restart_state(sandbox):
    client, _, _ = sandbox
    task_id = start(client).json()["task_id"]
    base = f"/api/v1/collections/jobs/{task_id}"
    assert client.post(base + "/continue").status_code == 409
    control.update(task_id, status="waiting_login", stage="authentication", message="等待登录")
    assert client.get(base).json()["status"] == "waiting_login"
    assert client.post(base + "/continue").json()["status"] == "running"
    assert control.consume_continue(task_id) is True
    assert control.consume_continue(task_id) is False
    assert client.post(base + "/cancel").json()["status"] == "cancelling"
    with pytest.raises(control.Cancelled):
        control.checkpoint(task_id)
    control.update(task_id, status="cancelled")
    assert client.post(base + "/continue").status_code == 409
    assert start(client).status_code == 202


def test_cancel_cannot_be_overwritten_by_progress(sandbox):
    client, _, _ = sandbox
    task_id = start(client).json()["task_id"]
    control.signal_task(task_id, "cancel")
    assert control.update(task_id, status="running")["status"] == "cancelling"
    assert control.update(task_id, status="completed")["status"] == "cancelled"


def test_worker_failure_and_expiry(sandbox, monkeypatch):
    client, _, _ = sandbox
    monkeypatch.setattr(control.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("SECRET")))
    state = start(client).json()
    assert state["status"] == "failed" and "SECRET" not in json.dumps(state)
    # 新任务状态在服务重建后仍可读取；超时异常任务不永久锁住采集。
    with control.store() as db:
        state.update(status="starting")
        db.execute("UPDATE tasks SET state=?,created=? WHERE id=?", (json.dumps(state), time.time() - 1300, state["task_id"]))
    assert control.get_task(state["task_id"])["error_type"] == "TaskExpired"


def test_completed_preview_cached_and_expired(sandbox):
    client, _, root = sandbox
    task_id = start(client).json()["task_id"]
    base = f"/api/v1/collections/jobs/{task_id}/preview"
    assert client.post(base).status_code == 409
    path = root / "data/raw/pdf/schedule.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"academic_year": "2026-2027", "semester": 1, "source_note": "测试",
        "courses": [{"course_key": "a", "course_name": "测试", "credits": "2", "meetings": []}]}), encoding="utf-8")
    control.update(task_id, status="completed", raw_file="data/raw/pdf/schedule.json")
    preview = client.post(base)
    assert preview.status_code == 200
    old_id = preview.json()["preview_id"]
    assert client.post(base).json()["preview_id"] == old_id
    with management._store() as db:
        db.execute("UPDATE previews SET expires=0 WHERE id=?", (old_id,))
    assert client.post(base).json()["preview_id"] != old_id
    # 完成采集和创建预览均未调用导入；测试只有本地暂存文件。
    assert not (root / "data/uploads").exists()


def test_preview_rejects_external_path(sandbox):
    client, _, _ = sandbox
    task_id = start(client).json()["task_id"]
    control.update(task_id, status="completed", raw_file="../../outside.json")
    assert client.post(f"/api/v1/collections/jobs/{task_id}/preview").status_code == 400


def test_worker_failure_redacted_and_cancelled(sandbox, monkeypatch):
    client, _, _ = sandbox
    logs = []
    monkeypatch.setattr(worker.CollectionTask, "write", lambda self, status, error_type=None: logs.append(status))
    monkeypatch.setattr(worker, "run_collection", lambda task: (_ for _ in ()).throw(ValueError("password=SECRET")))
    task_id = start(client).json()["task_id"]
    worker.execute(task_id)
    state = control.get_task(task_id)
    assert state["status"] == "failed" and state["error_type"] == "ValueError"
    assert "SECRET" not in json.dumps(state)
    assert logs == ["started", "failed"]
    monkeypatch.setattr(worker, "run_collection", lambda task: (_ for _ in ()).throw(control.Cancelled()))
    task_id = start(client).json()["task_id"]
    worker.execute(task_id)
    assert control.get_task(task_id)["status"] == "cancelled"


def test_login_continue_rechecks_and_returns_home(sandbox, monkeypatch):
    client, _, _ = sandbox
    task_id = start(client).json()["task_id"]
    class Page:
        url = worker.HOME
        attempts = 0
        def is_closed(self): return False
        def evaluate(self, script, kind): return self.attempts >= 2
        def wait_for_timeout(self, ms): pass
    page = Page()
    class Context:
        pages = [page]
    def continue_click(id):
        assert control.get_task(id)["status"] == "waiting_login"
        if page.attempts == 1:
            assert "已收到继续请求" in control.get_task(id)["message"]
        page.attempts += 1
        return True
    monkeypatch.setattr(control, "consume_continue", continue_click)
    assert worker.ensure_login(task_id, Context(), page, "grades") is page
    assert page.attempts == 2  # 第一次未登录，第二次成功；不会直接执行查询。


@pytest.mark.parametrize("kind", ["grades", "schedule", "requirements"])
def test_worker_success_reuses_functions_and_closes_browser(sandbox, monkeypatch, kind):
    client, _, root = sandbox
    import app.core.collection_log as collection_log
    monkeypatch.setattr(collection_log, "PROJECT_ROOT", root)
    logs, operations, closed = [], [], []
    monkeypatch.setattr(worker.CollectionTask, "write", lambda self, status, error_type=None: logs.append(status))
    class Button:
        def click(self, **kwargs): operations.append("click")
        def check(self): operations.append("excel")
        def is_checked(self): return True
    class Download:
        suggested_filename = "export.xlsx" if kind == "grades" else "export.pdf"
        def save_as(self, path):
            from pathlib import Path
            Path(path).write_bytes(b"test raw bytes")
    class Page:
        url = worker.HOME
        def is_closed(self): return False
        def goto(self, url, **kwargs): self.url = url
        def evaluate(self, *args): return True
        def wait_for_timeout(self, ms): pass
        def wait_for_function(self, *args, **kwargs): pass
        def get_by_role(self, *args, **kwargs): return Button()
        def locator(self, *args): return Button()
        def content(self): return "<html>test plan</html>"
        @contextmanager
        def expect_popup(self, **kwargs): yield SimpleNamespace(value=Page())
        @contextmanager
        def expect_download(self, **kwargs): yield SimpleNamespace(value=Download())
    class Context:
        def __init__(self): self.pages = []
        def set_default_timeout(self, value): pass
        def new_page(self):
            page = Page()
            self.pages.append(page)
            return page
        def storage_state(self, path): operations.append("save_auth")
    class Browser:
        def new_context(self, **kwargs): return Context()
        def close(self): closed.append(True)
    @contextmanager
    def playwright(): yield SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: Browser()))
    monkeypatch.setattr(worker, "sync_playwright", playwright)
    def filtered(page, year, semester):
        assert (year, semester) == ("2026-2027", 1)
        operations.append("filter")
    def queried(page, year, semester): operations.append("query")
    def validated(path, year, semester):
        assert path.is_file() and (year, semester) == ("2026-2027", 1)
        operations.append("validate")
        return {"records": 1}
    monkeypatch.setattr(worker.grades, "set_filters", filtered)
    monkeypatch.setattr(worker.grades, "query_grades", queried)
    monkeypatch.setattr(worker.grades, "validate_download", validated)
    monkeypatch.setattr(worker.schedule, "set_schedule_filters", filtered)
    monkeypatch.setattr(worker.schedule, "query_schedule", queried)
    monkeypatch.setattr(worker.schedule, "validate_schedule_pdf", validated)
    monkeypatch.setattr(worker, "expand_requirement_sections", lambda page: operations.append("expand"))
    monkeypatch.setattr(worker, "parse_requirements_html", lambda html: [SimpleNamespace(courses=[1])])
    response = client.post("/api/v1/collections/jobs", json={"data_type": kind} if kind == "requirements" else {
        "data_type": kind, "academic_year": "2026-2027", "semester": 1})
    task_id = response.json()["task_id"]
    worker.execute(task_id)
    state = control.get_task(task_id)
    assert state["status"] == "completed"
    assert (root / state["raw_file"]).is_file()
    assert logs == ["started", "validated"]
    assert closed == [True]
    if kind == "requirements": assert "expand" in operations
    else: assert all(operation in operations for operation in ["filter", "query", "validate"])
    if kind == "grades": assert "excel" in operations
    assert not (root / "data/uploads").exists()
