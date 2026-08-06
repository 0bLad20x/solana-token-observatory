from datetime import datetime, timezone

from jupiter_data_transform.collector import collect_once
from jupiter_data_transform.jupiter import FetchedToken
from jupiter_data_transform.repository import StoreSummary


class FakeClient:
    def fetch_tokens(self, mints: list[str]) -> list[FetchedToken]:
        return [
            FetchedToken(
                received_at=datetime.now(timezone.utc),
                payload={"id": mint},
            )
            for mint in mints
        ]


class FakeRepository:
    def __init__(self) -> None:
        self.rows: list[FetchedToken] = []

    def store_many(self, fetched_tokens: list[FetchedToken]) -> StoreSummary:
        self.rows.extend(fetched_tokens)
        return StoreSummary(inserted=len(fetched_tokens), repeated=0)


def test_collect_once_persists_every_returned_token() -> None:
    repository = FakeRepository()

    summary = collect_once(FakeClient(), repository, ["mint-a", "mint-b"])

    assert summary == StoreSummary(inserted=2, repeated=0)
    assert [row.payload["id"] for row in repository.rows] == ["mint-a", "mint-b"]
