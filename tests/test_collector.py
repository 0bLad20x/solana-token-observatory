from datetime import datetime, timezone
from uuid import uuid4

from jupiter_data_transform.collector import Collector
from jupiter_data_transform.models import FetchedToken


class FakeClient:
    async def fetch_tokens(self, mints: list[str]) -> list[FetchedToken]:
        return [
            FetchedToken(
                request_id=uuid4(),
                received_at=datetime.now(timezone.utc),
                payload={"id": mint},
            )
            for mint in mints
        ]


class FakeRepository:
    def __init__(self) -> None:
        self.rows: list[FetchedToken] = []

    async def store(self, fetched: FetchedToken) -> int:
        self.rows.append(fetched)
        return len(self.rows)


async def test_collect_once_persists_every_returned_token() -> None:
    repository = FakeRepository()
    collector = Collector(FakeClient(), repository)

    count = await collector.collect_once(["mint-a", "mint-b"])

    assert count == 2
    assert [row.payload["id"] for row in repository.rows] == ["mint-a", "mint-b"]
