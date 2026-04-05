"""Bootstrap and apply numbered SQL migrations for Grimnir."""

from __future__ import annotations

import hashlib
import re
from importlib import resources
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError, ProgrammingError

MIGRATION_LOCK_ID = 0x4752494D4E4952
MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""
MIGRATION_FILENAME_RE = re.compile(r"^(?P<version>\d+)_.*\.sql$")
DATABASE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def run_migrations(database_url: str) -> None:
    """Ensure the target database exists and apply pending SQL migrations."""
    sync_url = _to_sync_url(database_url)
    _ensure_database_exists(sync_url)

    engine = create_engine(sync_url, future=True, pool_pre_ping=True)
    try:
        raw_connection = engine.raw_connection()
        try:
            with raw_connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
                try:
                    cursor.execute(MIGRATION_TABLE_SQL)
                    raw_connection.commit()

                    cursor.execute("SELECT version, checksum FROM schema_migrations")
                    applied = {version: checksum for version, checksum in cursor.fetchall()}

                    for version, sql_text in _load_migrations():
                        checksum = hashlib.sha256(sql_text.encode("utf-8")).hexdigest()
                        if version in applied:
                            if applied[version] != checksum:
                                raise RuntimeError(
                                    f"Migration {version} checksum mismatch; manual intervention required"
                                )
                            continue

                        cursor.execute(sql_text)
                        cursor.execute(
                            """
                            INSERT INTO schema_migrations (version, checksum)
                            VALUES (%s, %s)
                            """,
                            (version, checksum),
                        )
                        raw_connection.commit()
                except Exception:
                    raw_connection.rollback()
                    raise
                finally:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))
                    raw_connection.commit()
        finally:
            raw_connection.close()
    finally:
        engine.dispose()


def _to_sync_url(database_url: str) -> str:
    url = make_url(database_url)
    drivername = url.drivername
    if drivername == "postgresql+asyncpg":
        url = url.set(drivername="postgresql+psycopg2")
    return url.render_as_string(hide_password=False)


def _ensure_database_exists(sync_url: str) -> None:
    engine = None
    try:
        engine = create_engine(sync_url, future=True, pool_pre_ping=True)
        with engine.connect():
            return
    except OperationalError as exc:
        if "does not exist" not in str(exc).lower():
            raise
    finally:
        try:
            engine.dispose()
        except Exception:
            pass

    url = make_url(sync_url)
    database_name = url.database
    if not database_name or not DATABASE_NAME_RE.fullmatch(database_name):
        raise RuntimeError("Cannot auto-create database for an unsafe database name")

    admin_url: URL = url.set(database="postgres")
    admin_engine = create_engine(
        admin_url.render_as_string(hide_password=False),
        future=True,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    except ProgrammingError as exc:
        if "already exists" not in str(exc).lower():
            raise
    finally:
        admin_engine.dispose()


def _load_migrations() -> list[tuple[str, str]]:
    migrations: list[tuple[str, str]] = []

    resource_dir = resources.files("csi_models").joinpath("sql")
    if resource_dir.exists():
        for entry in resource_dir.iterdir():
            if not entry.is_file():
                continue
            match = MIGRATION_FILENAME_RE.match(entry.name)
            if match is None:
                continue
            migrations.append((match.group("version"), entry.read_text(encoding="utf-8")))

    if migrations:
        migrations.sort(key=lambda item: int(item[0]))
        return migrations

    source_sql = Path(__file__).resolve().parents[2] / "001_schema.sql"
    match = MIGRATION_FILENAME_RE.match(source_sql.name)
    if match is None:
        raise RuntimeError("Could not resolve bundled migrations")
    migrations.append((match.group("version"), source_sql.read_text(encoding="utf-8")))
    migrations.sort(key=lambda item: int(item[0]))
    return migrations
