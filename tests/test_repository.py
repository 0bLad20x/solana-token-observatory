from datetime import datetime, timedelta, timezone

import jupiter_data_transform.repository as repository_module
from jupiter_data_transform.jupiter import FetchedToken
from jupiter_data_transform.repository import (
    JupiterRepository,
    StoreSummary,
    content_payload_hash,
    raw_payload_hash,
    source_updated_at,
)


def test_raw_hash_ignores_json_key_order() -> None:
    first = {"id": "mint-1", "usdPrice": 1.0, "holderCount": 10}
    second = {"holderCount": 10, "usdPrice": 1.0, "id": "mint-1"}

    assert raw_payload_hash(first) == raw_payload_hash(second)


def test_content_hash_ignores_only_updated_at() -> None:
    first = {
        "id": "mint-1",
        "updatedAt": "2026-08-06T12:00:00Z",
        "usdPrice": 1.0,
    }
    second = {
        "id": "mint-1",
        "updatedAt": "2026-08-06T12:00:10Z",
        "usdPrice": 1.0,
    }

    assert raw_payload_hash(first) != raw_payload_hash(second)
    assert content_payload_hash(first) == content_payload_hash(second)


def test_same_updated_at_does_not_hide_content_change() -> None:
    first = {
        "id": "mint-1",
        "updatedAt": "2026-08-06T12:00:00Z",
        "usdPrice": 1.0,
    }
    second = {
        "id": "mint-1",
        "updatedAt": "2026-08-06T12:00:00Z",
        "usdPrice": 2.0,
    }

    assert source_updated_at(first) == source_updated_at(second)
    assert content_payload_hash(first) != content_payload_hash(second)


def test_source_updated_at_parses_documented_timestamp() -> None:
    payload = {"id": "mint-1", "updatedAt": "2026-08-06T12:00:00Z"}

    assert source_updated_at(payload) == datetime(
        2026,
        8,
        6,
        12,
        0,
        tzinfo=timezone.utc,
    )


class FakeCursor:
    def __init__(self, row: tuple[str] | None = None) -> None:
        self._row = row

    def fetchone(self) -> tuple[str] | None:
        return self._row


class FakeConnection:
    def __init__(self) -> None:
        self.payload_keys: set[tuple[str, str]] = set()
        self.observations: list[tuple[object, ...]] = []

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] | None = None,
    ) -> FakeCursor:
        parameters = parameters or ()
        if "INSERT INTO jupiter_payloads" in statement:
            key = (str(parameters[0]), str(parameters[1]))
            if key in self.payload_keys:
                return FakeCursor()
            self.payload_keys.add(key)
            return FakeCursor((key[1],))

        if "INSERT INTO jupiter_observations" in statement:
            self.observations.append(parameters)
            return FakeCursor()

        raise AssertionError(f"unexpected SQL: {statement}")


def test_store_many_records_every_poll_and_deduplicates_payload(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(
        repository_module.psycopg,
        "connect",
        lambda _: connection,
    )

    received_at = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    payload = {
        "id": "mint-1",
        "updatedAt": "2026-08-06T11:59:58Z",
        "usdPrice": 1.0,
    }
    fetched_tokens = [
        FetchedToken(received_at=received_at, payload=payload),
        FetchedToken(received_at=received_at + timedelta(seconds=1), payload=payload),
    ]

    summary = JupiterRepository("postgresql://unused").store_many(fetched_tokens)

    assert summary == StoreSummary(observations=2, new_payloads=1)
    assert len(connection.payload_keys) == 1
    assert len(connection.observations) == 2
