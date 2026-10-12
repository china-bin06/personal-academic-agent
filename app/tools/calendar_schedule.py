from datetime import timedelta

from app.services import academic_calendar as calendar
from app.schemas.tool_params import ScheduleParams
from app.tools.schedules import get_schedule


def get_schedule_for_date(session, params, owner_id):
    target = params.target_date
    if target is None:
        offset = {"今天": 0, "明天": 1, "后天": 2}[params.relative_day]
        target = calendar.current_time().date() + timedelta(days=offset)
    config = calendar.load_config(owner_id)
    result = {"snapshot_id": None, "items": [], "unscheduled_courses": [], "target_date": target,
              "weekday": target.isoweekday(), "resolution_status": "needs_configuration",
              "note": "尚未同步当前学期开学日期，请在开学日期同步页确认学年、学期及第一教学周周一，再查询日期课表。"}
    if config is None:
        return result
    result.update(academic_year=config.academic_year, semester=config.semester, first_monday=config.first_monday,
                  calendar_updated_at=config.updated_at)
    delta = (target - config.first_monday).days
    if delta < 0 or delta >= config.teaching_weeks * 7:
        result.update(resolution_status="out_of_term", note="该日期超出已确认学期的教学周范围，不能据此认定没有课。请确认日期或更新当前学期开学配置。")
        return result
    week = delta // 7 + 1
    result.update(get_schedule(session, ScheduleParams(academic_year=config.academic_year,
                  semester=config.semester, week=week, weekday=target.isoweekday()), owner_id))
    result.update(resolution_status="resolved", week=week)
    result["note"] += f"；{target.isoformat()}按已确认开学日期换算为第{week}教学周，星期{target.isoweekday()}。"
    return result
