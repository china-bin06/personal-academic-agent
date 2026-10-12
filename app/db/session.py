from sqlalchemy import create_engine

from app.core.config import settings

engine = create_engine(
    settings.database_url.get_secret_value(),
    pool_pre_ping=True,
    connect_args={
        "connect_timeout": 3,
        "options": "-c statement_timeout=3000",
    },
)