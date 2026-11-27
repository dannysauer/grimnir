"""Migration runner tests against a real TimescaleDB database."""

from __future__ import annotations

from collections.abc import Callable

import psycopg2
import pytest
from csi_models.migrate import run_migrations

# Columns and indexes in the public schema, which a no-op run must not change.
_CATALOG_SQL = """
SELECT 'column', table_name, column_name, data_type
  FROM information_schema.columns WHERE table_schema = 'public'
UNION ALL
SELECT 'index', tablename, indexname, indexdef
  FROM pg_indexes WHERE schemaname = 'public'
ORDER BY 1, 2, 3
"""


def _snapshot(dsn: str) -> tuple[list[tuple], list[tuple]]:
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT version, checksum, applied_at FROM schema_migrations ORDER BY version"
            )
            applied = cursor.fetchall()
            cursor.execute(_CATALOG_SQL)
            return applied, cursor.fetchall()
    finally:
        conn.close()


# Verifies GRM-010: applying migrations to a current database changes nothing,
# neither the migration record nor the schema.
def test_run_migrations_twice_is_a_no_op(
    make_database: Callable[[], str], to_sync_dsn: Callable[[str], str]
) -> None:
    url = make_database()

    run_migrations(url)
    first = _snapshot(to_sync_dsn(url))
    run_migrations(url)
    second = _snapshot(to_sync_dsn(url))

    assert first[0], "the first run should record at least one migration"
    assert second == first


# Verifies GRM-011: run_migrations, which Geri and Freki call at startup,
# refuses an applied migration whose checksum changed.
def test_run_migrations_refuses_a_checksum_mismatch(
    make_database: Callable[[], str], to_sync_dsn: Callable[[str], str]
) -> None:
    url = make_database()
    run_migrations(url)

    conn = psycopg2.connect(to_sync_dsn(url))
    try:
        with conn, conn.cursor() as cursor:
            cursor.execute(
                "UPDATE schema_migrations SET checksum = 'tampered' WHERE version = '001'"
            )
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="Migration 001 checksum mismatch"):
        run_migrations(url)
