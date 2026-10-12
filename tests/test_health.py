from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_health():
    # 集成测试：需要本地 PostgreSQL 已启动
    response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
    }


def test_database_unavailable():
    error = OperationalError(
        statement=None,
        params=None,
        orig=Exception("simulated connection failure"),
    )

    with patch("app.main.engine.connect", side_effect=error):
        response = client.get("/health/db")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "数据库暂不可用",
    }