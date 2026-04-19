from __future__ import annotations

from collections.abc import Sequence


class FakeScalarSequence:
    def __init__(self, values: Sequence[object]):
        self._values = list(values)

    def all(self) -> list[object]:
        return list(self._values)


class FakeExecuteResult:
    def __init__(
        self,
        *,
        all_rows: Sequence[object] | None = None,
        scalar_value: object | None = None,
        first_value: object | None = None,
        one_value: object | None = None,
        scalars_values: Sequence[object] | None = None,
    ) -> None:
        self._all_rows = list(all_rows or [])
        self._scalar_value = scalar_value
        self._first_value = first_value
        self._one_value = one_value
        self._scalars_values = list(scalars_values or [])

    def all(self) -> list[object]:
        return list(self._all_rows)

    def scalar_one_or_none(self) -> object | None:
        return self._scalar_value

    def scalar_one(self) -> object:
        if self._scalar_value is None:
            raise AssertionError("Expected scalar value, got None")
        return self._scalar_value

    def first(self) -> object | None:
        return self._first_value

    def one(self) -> object:
        if self._one_value is None:
            raise AssertionError("Expected one() value, got None")
        return self._one_value

    def one_or_none(self) -> object | None:
        return self._one_value

    def scalars(self) -> FakeScalarSequence:
        return FakeScalarSequence(self._scalars_values)


class FakeSession:
    def __init__(
        self,
        *,
        execute_results: Sequence[FakeExecuteResult | object] | None = None,
        scalar_results: Sequence[object] | None = None,
        flush_exception: Exception | None = None,
    ) -> None:
        self.execute_results = list(execute_results or [])
        self.scalar_results = list(scalar_results or [])
        self.flush_exception = flush_exception
        self.execute_calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []
        self.scalar_calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshes = 0
        self.flushes = 0

    async def execute(self, statement: object, *args: object, **kwargs: object) -> object:
        self.execute_calls.append((statement, args, kwargs))
        if not self.execute_results:
            raise AssertionError("Unexpected execute() call")
        result = self.execute_results.pop(0)
        return result

    async def scalar(self, statement: object, *args: object, **kwargs: object) -> object:
        self.scalar_calls.append((statement, args, kwargs))
        if not self.scalar_results:
            raise AssertionError("Unexpected scalar() call")
        return self.scalar_results.pop(0)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def delete(self, obj: object) -> None:
        self.deleted.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, _obj: object) -> None:
        self.refreshes += 1

    async def flush(self) -> None:
        self.flushes += 1
        if self.flush_exception is not None:
            raise self.flush_exception


class _FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> FakeSession:
        return self._session

    async def __aexit__(self, *_exc: object) -> None:
        return None


class FakeSessionFactory:
    def __init__(self, sessions: Sequence[FakeSession]) -> None:
        self._sessions = list(sessions)

    def __call__(self) -> _FakeSessionContext:
        if not self._sessions:
            raise AssertionError("No fake sessions left in factory")
        return _FakeSessionContext(self._sessions.pop(0))
