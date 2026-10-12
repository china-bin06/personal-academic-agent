from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import engine

from app.api.chat import router as chat_router
from app.api.data_management import router as data_router
from app.api.collection_control import router as collection_router
from app.api.academic_calendar import router as calendar_router

app = FastAPI(title="个人学业 Agent", version="0.2.0")

app.include_router(chat_router)
app.include_router(data_router)
app.include_router(collection_router)
app.include_router(calendar_router)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)


@app.get("/", include_in_schema=False)
def homepage():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/health/db")
def database_health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="数据库暂不可用",
        ) from None

    return {"status": "ok", "database": "ok"}
