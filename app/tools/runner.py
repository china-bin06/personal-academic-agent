from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Callable
from uuid import uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import (
    SQLAlchemyError,
    TimeoutError as SQLAlchemyTimeoutError,
)
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.db.read_session import read_engine

from app.schemas.tool_params import (
    CompareTermsParams,
    DegreeProgressParams,
    GradeSummaryParams,
    ScheduleParams,
)
from app.schemas.tool_results import (
    CompareTermsResult,
    DegreeProgressResult,
    GradeSummaryResult,
    ScheduleResult,
)

from app.tools.grades import (
    compare_terms,
    get_grade_summary,
)
from app.tools.requirements import get_degree_progress
from app.tools.schedules import get_schedule


@dataclass(frozen=True)
class ToolSpec:
    params_model: type[BaseModel]
    result_model: type[BaseModel]
    function: Callable


TOOLS = {
    "get_grade_summary": ToolSpec(
        GradeSummaryParams,
        GradeSummaryResult,
        get_grade_summary,
    ),
    "compare_terms": ToolSpec(
        CompareTermsParams,
        CompareTermsResult,
        compare_terms,
    ),
    "get_schedule": ToolSpec(
        ScheduleParams,
        ScheduleResult,
        get_schedule,
    ),
    "get_degree_progress": ToolSpec(
        DegreeProgressParams,
        DegreeProgressResult,
        get_degree_progress,
    ),
}


def validation_details(error: ValidationError):
    # 不返回 input 和 ctx，避免回显不必要的输入，
    # 也避免 ValueError 等对象无法转换成 JSON。
    return [
        {
            "field": ".".join(map(str, item["loc"])),
            "message": item["msg"],
        }
        for item in error.errors()
    ]


def run_tool(
    tool_name: str,
    arguments: dict,
    *,
    owner_id: str,
):
    request_id = uuid4().hex
    started = perf_counter()

    status = "error"
    error_code = None
    validated_params = {}

    def failure(code, message, details=None):
        nonlocal error_code

        error_code = code

        return {
            "request_id": request_id,
            "status": "error",
            "tool": tool_name,
            "data": None,
            "error": {
                "code": code,
                "message": message,
                "details": details,
            },
        }

    try:
        spec = TOOLS.get(tool_name)

        if spec is None:
            return failure(
                "UNKNOWN_TOOL",
                "工具未注册，拒绝执行",
            )

        try:
            params = spec.params_model.model_validate(arguments)
        except ValidationError as error:
            return failure(
                "INVALID_ARGUMENTS",
                "工具参数不合法",
                validation_details(error),
            )

        validated_params = params.model_dump(mode="json")

        try:
            with Session(read_engine) as session:
                raw_result = spec.function(
                    session,
                    params,
                    owner_id,
                )

        except SQLAlchemyTimeoutError:
            return failure(
                "DATABASE_TIMEOUT",
                "等待数据库连接超时",
            )

        except SQLAlchemyError as error:
            sqlstate = getattr(
                getattr(error, "orig", None),
                "sqlstate",
                None,
            )

            if sqlstate == "57014":
                return failure(
                    "QUERY_CANCELLED",
                    "数据库查询被取消，可能达到查询时限",
                )

            return failure(
                "DATABASE_ERROR",
                "数据库查询失败，请检查数据库状态",
            )

        except ValueError:
            return failure(
                "QUERY_REJECTED",
                "查询超出工具允许范围或数据状态不符合要求",
            )

        try:
            result = spec.result_model.model_validate(raw_result)
        except ValidationError:
            return failure(
                "INVALID_RESULT",
                "工具返回结构异常，需要检查程序",
            )

        status = "success"

        return {
            "request_id": request_id,
            "status": "success",
            "tool": tool_name,
            "data": result.model_dump(mode="json"),
            "error": None,
        }

    except Exception:
        # 最外层保护；不把内部异常和连接信息返回用户。
        return failure(
            "INTERNAL_ERROR",
            "工具执行出现程序异常",
        )

    finally:
        write_audit(
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "request_id": request_id,
                "owner_id": owner_id,
                "tool": tool_name,
                "params": validated_params,
                "status": status,
                "error_code": error_code,
                "duration_ms": round(
                    (perf_counter() - started) * 1000,
                    2,
                ),
            }
        )