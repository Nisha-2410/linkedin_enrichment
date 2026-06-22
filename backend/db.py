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
    company_columns = (
        {column["name"] for column in inspector.get_columns("companies")}
        if "companies" in inspector.get_table_names()
        else set()
    )
    with engine.begin() as connection:
        if "display_name" not in columns:
            connection.execute(text("ALTER TABLE candidates ADD COLUMN display_name VARCHAR DEFAULT ''"))
        if company_columns and "domain" not in company_columns:
            connection.execute(text("ALTER TABLE companies ADD COLUMN domain VARCHAR"))
        if "opportunity_companies" in inspector.get_table_names():
            opportunity_company_columns = {
                column["name"] for column in inspector.get_columns("opportunity_companies")
            }
            if "contact_details" not in opportunity_company_columns:
                connection.execute(text("ALTER TABLE opportunity_companies ADD COLUMN contact_details TEXT"))
        # One-time backfill: earlier versions of this app stored opportunity-
        # scoring data (opportunity_score, city, state, job_role_posted,
        # supplier_type, ai_insight, and the even older combined
        # location_summary) directly on companies. OpportunityCompany is now
        # the only place that data lives going forward -- this copies
        # whatever's still sitting on the legacy companies columns into
        # opportunity_companies ONCE, matched by name, then never touches
        # those legacy columns again. They're left in place on companies
        # (SQLite can't cheaply drop columns) but the app code never reads
        # them after this point.
        legacy_opportunity_columns = {
            "opportunity_score", "city", "state", "job_role_posted", "supplier_type", "ai_insight",
        }
        if company_columns and legacy_opportunity_columns & company_columns and "opportunity_companies" in inspector.get_table_names():
            already_seeded = connection.execute(text("SELECT COUNT(*) FROM opportunity_companies")).scalar()
            if not already_seeded:
                has_location_summary = "location_summary" in company_columns
                city_expr = (
                    "CASE WHEN city IS NOT NULL AND city != '' THEN city "
                    "WHEN location_summary IS NOT NULL AND instr(location_summary, ',') > 0 "
                    "THEN trim(substr(location_summary, 1, instr(location_summary, ',') - 1)) "
                    "ELSE city END"
                    if has_location_summary else "city"
                )
                state_expr = (
                    "CASE WHEN state IS NOT NULL AND state != '' THEN state "
                    "WHEN location_summary IS NOT NULL AND instr(location_summary, ',') > 0 "
                    "THEN trim(substr(location_summary, instr(location_summary, ',') + 1)) "
                    "WHEN location_summary IS NOT NULL AND location_summary != '' THEN location_summary "
                    "ELSE state END"
                    if has_location_summary else "state"
                )
                connection.execute(
                    text(
                        f"""
                        INSERT INTO opportunity_companies
                            (name, display_name, opportunity_score, city, state,
                             job_role_posted, supplier_type, ai_insight, created_at, updated_at)
                        SELECT
                            name, display_name, opportunity_score,
                            {city_expr}, {state_expr},
                            job_role_posted, supplier_type, ai_insight,
                            created_at, updated_at
                        FROM companies
                        WHERE opportunity_score IS NOT NULL
                           OR (supplier_type IS NOT NULL AND supplier_type != '')
                           OR (job_role_posted IS NOT NULL AND job_role_posted != '')
                        """
                    )
                )
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