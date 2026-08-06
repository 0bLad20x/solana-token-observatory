from datetime import datetime, timezone

from jupiter_data_transform.repository import (
    canonical_payload_hash,
    source_updated_at,
)


def test_hash_ignores_json_key_order() -> None:
    first = {"id": "mint-1", "usdPrice": 1.0, "holderCount": 10}
    second = {"holderCount": 10, "usdPrice": 1.0, "id": "mint-1"}

    assert canonical_payload_hash(first) == canonical_payload_hash(second)


def test_same_updated_at_does_not_define_same_payload() -> None:
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
    assert canonical_payload_hash(first) != canonical_payload_hash(second)


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
