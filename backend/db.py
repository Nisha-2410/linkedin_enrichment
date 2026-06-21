from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL


class Base(DeclarativeBase):
    pass


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db():
    from . import models  # noqa: F401

    Base.metadata.create_all(engine)
    _migrate_sqlite()


def _migrate_sqlite():
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    if "candidates" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("candidates")}
    observation_columns = {column["name"] for column in inspector.get_columns("observations")}
    with engine.begin() as connection:
        if "display_name" not in columns:
            connection.execute(text("ALTER TABLE candidates ADD COLUMN display_name VARCHAR DEFAULT ''"))
        for column_name, ddl in {
            "person_name": "VARCHAR",
            "companies_found": "JSON",
            "titles_found": "JSON",
            "locations_found": "JSON",
            "employment_indicators": "JSON",
            "raw_employment_status": "VARCHAR",
        }.items():
            if column_name not in observation_columns:
                connection.execute(text(f"ALTER TABLE observations ADD COLUMN {column_name} {ddl}"))
        connection.execute(
            text(
                """
                UPDATE candidates
                SET display_name = CASE
                    WHEN instr(raw_title, ' - ') > 0 THEN trim(substr(raw_title, 1, instr(raw_title, ' - ') - 1))
                    WHEN instr(raw_title, ' · ') > 0 THEN trim(substr(raw_title, 1, instr(raw_title, ' · ') - 1))
                    ELSE raw_title
                END
                WHERE display_name IS NULL OR display_name = ''
                """
            )
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

