from sqlalchemy import create_engine

from app.core.config import settings


read_engine = create_engine(
    settings.read_database_url.get_secret_value(),
    pool_pre_ping=True,
    pool_size=3,
    max_overflow=2,
    pool_timeout=3,
    connect_args={
        "connect_timeout": 3,
        "options": (
            "-c statement_timeout=3000 "
            "-c default_transaction_read_only=on"
        ),
    },
)