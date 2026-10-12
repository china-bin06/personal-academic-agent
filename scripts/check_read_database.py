from sqlalchemy import text

from app.db.read_session import read_engine


with read_engine.connect() as connection:
    print(
        "数据库用户：",
        connection.execute(text("SELECT current_user")).scalar(),
    )

    print(
        "只读事务：",
        connection.execute(
            text("SHOW transaction_read_only")
        ).scalar(),
    )

    print(
        "成绩数量：",
        connection.execute(
            text("SELECT COUNT(*) FROM grades")
        ).scalar(),
    )

    print(
        "是否具有写权限：",
        connection.execute(
            text(
                "SELECT has_table_privilege("
                "current_user, 'public.grades', 'INSERT')"
            )
        ).scalar(),
    )

read_engine.dispose()