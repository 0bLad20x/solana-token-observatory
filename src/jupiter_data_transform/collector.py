from __future__ import annotations

import logging
import time
from collections.abc import Sequence

from .jupiter import JupiterClient
from .repository import JupiterRepository, StoreSummary

LOGGER = logging.getLogger(__name__)


def collect_once(
    client: JupiterClient,
    repository: JupiterRepository,
    mints: Sequence[str],
) -> StoreSummary:
    fetched_tokens = client.fetch_tokens(mints)
    summary = repository.store_many(fetched_tokens)
    LOGGER.info(
        "collection_completed requested=%d received=%d inserted=%d repeated=%d",
        len(set(mints)),
        len(fetched_tokens),
        summary.inserted,
        summary.repeated,
    )
    return summary


def run(
    client: JupiterClient,
    repository: JupiterRepository,
    mints: Sequence[str],
    interval_seconds: float,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")

    while True:
        started = time.monotonic()
        try:
            collect_once(client, repository, mints)
        except Exception:
            LOGGER.exception("collection_failed")
        elapsed = time.monotonic() - started
        time.sleep(max(0.0, interval_seconds - elapsed))
