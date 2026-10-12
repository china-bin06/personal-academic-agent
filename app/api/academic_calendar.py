from fastapi import APIRouter, Request

from app.api.data_management import check_origin, guarded
from app.services import academic_calendar as service

router = APIRouter(prefix="/api/v1/calendar", tags=["academic-calendar"])


@router.get("", response_model=service.CalendarStatus)
def status():
    return guarded(service.get_status)


@router.put("", response_model=service.CalendarStatus)
def synchronize(params: service.CalendarInput, request: Request):
    check_origin(request)
    return guarded(service.save_config, params)
