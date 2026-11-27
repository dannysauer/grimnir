"""Shared pytest fixtures for tests that need a real PostgreSQL database.

Set ``GRIMNIR_TEST_DATABASE_URL`` to a superuser connection on a PostgreSQL
server that has the TimescaleDB extension available. Put the password in
``PGPASSWORD`` rather than the URL; both asyncpg and psycopg2 read it::

    PGPASSWORD=test
    GRIMNIR_TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:55432/postgres

Each test that asks for a database gets a new, empty one named
``grimnir_test_<random>``, which is dropped when the session ends. Without the
variable, those tests are skipped. A run that is killed can leave databases
behind; drop any ``grimnir_test_*`` database by hand.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator

import pytest
from sqlalchemy.engine import URL, make_url

TEST_DATABASE_URL_ENV = "GRIMNIR_TEST_DATABASE_URL"


def sync_dsn(url: URL | str) -> str:
    """Render a URL that psycopg2 accepts, whatever driver the input named."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def to_sync_dsn() -> Callable[[URL | str], str]:
    """Give tests the URL converter without importing this conftest."""
    return sync_dsn


@pytest.fixture(scope="session")
def test_database_url() -> URL:
    """The admin connection URL, or skip the test when none is configured."""
    raw = os.environ.get(TEST_DATABASE_URL_ENV)
    if not raw:
        pytest.skip(f"{TEST_DATABASE_URL_ENV} is not set")
    return make_url(raw)


@pytest.fixture(scope="session")
def make_database(test_database_url: URL) -> Iterator[Callable[[], str]]:
    """Return a factory that creates an empty database and returns its asyncpg URL."""
    import psycopg2  # imported here so tests without a database don't need it

    admin_dsn = sync_dsn(test_database_url)
    created: list[str] = []

    def _create() -> str:
        name = f"grimnir_test_{uuid.uuid4().hex[:12]}"
        conn = psycopg2.connect(admin_dsn)
        try:
            conn.autocommit = True
            with conn.cursor() as cursor:
                cursor.execute(f'CREATE DATABASE "{name}"')
        finally:
            conn.close()
        created.append(name)
        return (
            test_database_url.set(drivername="postgresql+asyncpg", database=name)
        ).render_as_string(hide_password=False)

    yield _create

    conn = psycopg2.connect(admin_dsn)
    try:
        conn.autocommit = True
        with conn.cursor() as cursor:
            for name in created:
                # Disconnect stragglers first; DROP ... WITH (FORCE) needs PostgreSQL 13+.
                try:
                    cursor.execute(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = %s AND pid <> pg_backend_pid()",
                        (name,),
                    )
                    cursor.execute(f'DROP DATABASE IF EXISTS "{name}"')
                except psycopg2.Error as exc:
                    print(f"could not drop test database {name}: {exc}")
    finally:
        conn.close()
