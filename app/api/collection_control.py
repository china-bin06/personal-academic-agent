from fastapi import APIRouter, Request

from app.api.data_management import check_origin, guarded
from app.services import collection_control as service
from app.services.data_management import Preview

router = APIRouter(prefix="/api/v1/collections/jobs", tags=["collection-control"])


@router.post("", response_model=service.CollectionState, status_code=202)
def start(params: service.CollectionRequest, request: Request):
    check_origin(request)
    return guarded(service.start_task, params)


@router.get("", response_model=list[service.CollectionState])
def jobs():
    return guarded(service.list_tasks)


@router.get("/{task_id}", response_model=service.CollectionState)
def job(task_id: str):
    return guarded(service.get_task, task_id)


@router.post("/{task_id}/continue", response_model=service.CollectionState)
def resume(task_id: str, request: Request):
    check_origin(request)
    return guarded(service.signal_task, task_id, "continue")


@router.post("/{task_id}/cancel", response_model=service.CollectionState)
def cancel(task_id: str, request: Request):
    check_origin(request)
    return guarded(service.signal_task, task_id, "cancel")


@router.post("/{task_id}/preview", response_model=Preview)
def preview(task_id: str, request: Request):
    check_origin(request)
    return guarded(service.preview_task, task_id)
