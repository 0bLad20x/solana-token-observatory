from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from jupiter_data_transform.models import FetchedToken, TokenSnapshot


def test_snapshot_extracts_state_and_rolling_values() -> None:
    fetched = FetchedToken(
        request_id=UUID("12345678-1234-5678-1234-567812345678"),
        received_at=datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc),
        payload={
            "id": "mint-1",
            "symbol": "TEST",
            "updatedAt": "2026-08-06T09:59:58Z",
            "usdPrice": 0.125,
            "mcap": 125000,
            "holderCount": 321,
            "stats5m": {
                "buyVolume": 1200.5,
                "sellVolume": 900.25,
                "numBuys": 42,
                "numSells": 31,
                "numTraders": 20,
                "holderChange": 1.5,
            },
        },
    )

    snapshot = TokenSnapshot.from_fetched(fetched)

    assert snapshot.mint == "mint-1"
    assert snapshot.usd_price == Decimal("0.125")
    assert snapshot.buy_volume_5m == Decimal("1200.5")
    assert snapshot.num_traders_5m == 20
    assert snapshot.source_updated_at == datetime(2026, 8, 6, 9, 59, 58, tzinfo=timezone.utc)
