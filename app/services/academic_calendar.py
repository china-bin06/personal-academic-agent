"""用户确认的当前学期日期配置与北京时间；仅保存本地日历设置。"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.tool_params import TermParams

ROOT = Path(__file__).resolve().parents[2]
STORE_PATH = ROOT / "data/calendar/settings.sqlite3"
SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")


def current_time():
    return datetime.now(SHANGHAI)


class CalendarInput(TermParams):
    first_monday: date
    teaching_weeks: int = Field(default=20, strict=True, ge=1, le=60)

    @model_validator(mode="after")
    def validate_monday(self):
        if self.first_monday.isoweekday() != 1:
            raise ValueError("请填写第一教学周的周一日期，不能用报到日期替代")
        if not date(int(self.academic_year[:4]), 8, 1) <= self.first_monday <= date(int(self.academic_year[5:]), 7, 31):
            raise ValueError("日期应在所选学年的8月至次年7月之间")
        return self


class CalendarConfig(CalendarInput):
    updated_at: datetime


class CalendarStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_time: datetime
    timezone: str = "Asia/Shanghai"
    configuration: CalendarConfig | None
    note: str = "日期按北京时间解释；第一教学周周一为第1周起点，不自动处理节假日或调课。"


@contextmanager
def store():
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(STORE_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS calendars (owner TEXT PRIMARY KEY, configuration TEXT NOT NULL)")
        with connection:
            yield connection
    finally:
        connection.close()


def load_config(owner="local"):
    if not STORE_PATH.is_file():
        return None
    with store() as connection:
        row = connection.execute("SELECT configuration FROM calendars WHERE owner=?", (owner,)).fetchone()
    return CalendarConfig.model_validate_json(row["configuration"]) if row else None


def get_status(owner="local"):
    return CalendarStatus(current_time=current_time(), configuration=load_config(owner))


def save_config(params, owner="local"):
    config = CalendarConfig(**params.model_dump(), updated_at=current_time())
    with store() as connection:
        connection.execute("INSERT INTO calendars VALUES (?,?) ON CONFLICT(owner) DO UPDATE SET configuration=excluded.configuration",
                           (owner, config.model_dump_json()))
    return CalendarStatus(current_time=current_time(), configuration=config)
