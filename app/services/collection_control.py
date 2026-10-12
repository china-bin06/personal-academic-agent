"""页面采集任务：固定入口、单任务、持久状态；不执行客户端命令。"""
import json
import re
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from uuid import uuid4
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services import data_management as management

ROOT = management.ROOT
STORE_PATH = ROOT / "data" / "collections" / "tasks.sqlite3"
TERMINAL = {"completed", "failed", "cancelled"}
MAX_SECONDS = 15 * 60


class CollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data_type: Literal["grades", "schedule", "requirements"]
    academic_year: str | None = Field(default=None, pattern=r"^\d{4}-\d{4}$")
    semester: int | None = Field(default=None, strict=True, ge=1, le=3)

    @model_validator(mode="after")
    def validate_term(self):
        if self.data_type == "requirements":
            if self.academic_year is not None or self.semester is not None:
                raise ValueError("培养计划无需学年学期")
        else:
            if self.academic_year is None or self.semester is None:
                raise ValueError("成绩和课表必须选择学年学期")
            start, end = map(int, self.academic_year.split("-"))
            if end != start + 1:
                raise ValueError("学年必须为连续两年")
        return self


class CollectionState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    data_type: Literal["grades", "schedule", "requirements"]
    academic_year: str | None = None
    semester: int | None = None
    status: Literal["starting", "running", "waiting_login", "cancelling", "completed", "failed", "cancelled"]
    stage: str
    message: str
    started_at: datetime
    updated_at: datetime
    raw_file: str | None = None
    error_type: str | None = None
    preview_id: str | None = None


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def store():
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(STORE_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, state TEXT NOT NULL, created REAL NOT NULL, cancel INTEGER DEFAULT 0, resume INTEGER DEFAULT 0)")
    db.commit()
    try:
        with db:
            yield db
    finally:
        db.close()


def row_for(db, task_id):
    if not re.fullmatch(r"[0-9a-f]{32}", task_id):
        raise management.ManagementError("TASK_NOT_FOUND", "采集任务不存在", 404)
    row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        raise management.ManagementError("TASK_NOT_FOUND", "采集任务不存在", 404)
    return row


def expire_tasks(db):
    # Worker每阶段检查15分钟期限；额外留5分钟给有界浏览器操作及清理。
    for row in db.execute("SELECT * FROM tasks WHERE created < ?", (time.time() - MAX_SECONDS - 300,)).fetchall():
        state = json.loads(row["state"])
        if state["status"] not in TERMINAL:
            state.update(status="failed", message="采集超时或进程已中断，请关闭遗留采集浏览器后重试。", error_type="TaskExpired", updated_at=now())
            db.execute("UPDATE tasks SET state=?, cancel=1 WHERE id=?", (json.dumps(state), row["id"]))


def update(task_id, **values):
    with store() as db:
        db.execute("BEGIN IMMEDIATE")
        row = row_for(db, task_id)
        state = json.loads(row["state"])
        if state["status"] in TERMINAL:
            return state
        if row["cancel"] and values.get("status") in {"running", "waiting_login", "completed"}:
            if values["status"] == "completed":
                values.update(status="cancelled", message="采集已取消，未导入数据库。")
            else:
                values.update(status="cancelling", message="已请求取消，等待当前浏览器操作结束并关闭窗口。")
        state.update(values, updated_at=now())
        # 不接受异常原文、URL、凭据；所有message均来自固定文案。
        state = CollectionState.model_validate(state).model_dump(mode="json")
        db.execute("UPDATE tasks SET state=? WHERE id=?", (json.dumps(state, ensure_ascii=False), task_id))
        return state


def get_task(task_id):
    with store() as db:
        expire_tasks(db)
        return json.loads(row_for(db, task_id)["state"])


def list_tasks():
    with store() as db:
        expire_tasks(db)
        return [json.loads(row["state"]) for row in db.execute("SELECT state FROM tasks ORDER BY created DESC LIMIT 50")]


def monitor(process, task_id):
    try:
        code = process.wait()
        state = get_task(task_id)
        if state["status"] not in TERMINAL:
            update(task_id, status="cancelled" if state["status"] == "cancelling" else "failed",
                   message="采集进程已结束，请查看状态后重试。", error_type=f"WorkerExit{code}")
    except Exception:
        update(task_id, status="failed", message="无法确认采集进程状态，请关闭采集浏览器后重试。", error_type="WorkerMonitorError")


def start_task(params):
    task_id = uuid4().hex
    state = CollectionState(task_id=task_id, **params.model_dump(), status="starting", stage="browser_launch",
                            message="正在打开本机Edge，请留意新窗口。", started_at=now(), updated_at=now()).model_dump(mode="json")
    with store() as db:
        db.execute("BEGIN IMMEDIATE")
        expire_tasks(db)
        for row in db.execute("SELECT state FROM tasks"):
            if json.loads(row["state"])["status"] not in TERMINAL:
                raise management.ManagementError("TASK_BUSY", "已有采集任务，请先完成或取消该任务。", 409)
        db.execute("INSERT INTO tasks(id,state,created) VALUES(?,?,?)", (task_id, json.dumps(state, ensure_ascii=False), time.time()))
    try:
        process = subprocess.Popen([sys.executable, "-m", "scripts.collect_from_page", "--task-id", task_id],
                                   cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, shell=False,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=monitor, args=(process, task_id), daemon=True).start()
    except OSError:
        return update(task_id, status="failed", message="采集进程启动失败，请检查Python环境。", error_type="WorkerStartError")
    return get_task(task_id)


def signal_task(task_id, action):
    with store() as db:
        db.execute("BEGIN IMMEDIATE")
        state = json.loads(row_for(db, task_id)["state"])
        if state["status"] in TERMINAL:
            raise management.ManagementError("TASK_FINISHED", "任务已结束，不能继续或取消。", 409)
        if action == "continue":
            if state["status"] != "waiting_login":
                raise management.ManagementError("TASK_NOT_WAITING", "任务当前未等待登录。", 409)
            db.execute("UPDATE tasks SET resume=1 WHERE id=?", (task_id,))
            state.update(status="running", message="正在检查登录状态……")
        else:
            db.execute("UPDATE tasks SET cancel=1 WHERE id=?", (task_id,))
            state.update(status="cancelling", message="已请求取消，等待当前浏览器操作结束并关闭窗口。")
        state["updated_at"] = now()
        db.execute("UPDATE tasks SET state=? WHERE id=?", (json.dumps(state, ensure_ascii=False), task_id))
    return state


class Cancelled(Exception):
    pass


def checkpoint(task_id):
    with store() as db:
        row = row_for(db, task_id)
        state = json.loads(row["state"])
        if row["cancel"] or state["status"] in TERMINAL:
            raise Cancelled()
        if time.time() - row["created"] > MAX_SECONDS:
            raise TimeoutError("task deadline")


def consume_continue(task_id):
    with store() as db:
        db.execute("BEGIN IMMEDIATE")
        row = row_for(db, task_id)
        if row["resume"]:
            db.execute("UPDATE tasks SET resume=0 WHERE id=?", (task_id,))
            return True
        return False


def preview_task(task_id):
    with store() as db:
        db.execute("BEGIN IMMEDIATE")
        state = json.loads(row_for(db, task_id)["state"])
        if state["status"] != "completed" or not state["raw_file"]:
            raise management.ManagementError("TASK_NOT_READY", "任务尚未完成校验，不能预览。", 409)
        if state["preview_id"]:
            with closing(management._store()) as previews:
                row = previews.execute("SELECT preview, expires FROM previews WHERE id=? AND owner='local'", (state["preview_id"],)).fetchone()
                if row and row["expires"] > time.time():
                    return management.Preview.model_validate_json(row["preview"])
        path = (ROOT / state["raw_file"]).resolve()
        if not path.is_relative_to((ROOT / "data/raw").resolve()):
            raise management.ManagementError("TASK_FILE", "采集文件路径异常")
        if not path.is_file() or path.stat().st_size > management.MAX_BYTES:
            raise management.ManagementError("TASK_FILE", "采集文件不存在或超过10MB")
        preview = management.create_preview(state["data_type"], path.name, path.read_bytes())
        state["preview_id"] = preview.preview_id
        db.execute("UPDATE tasks SET state=? WHERE id=?", (json.dumps(state, ensure_ascii=False), task_id))
        return preview
