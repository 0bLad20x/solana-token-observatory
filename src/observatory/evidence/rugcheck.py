from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

RUGCHECK_REPORT_URL = "https://api.rugcheck.xyz/v1/tokens/{mint}/report"
RUGCHECK_TIMEOUT_SECONDS = 20.0
_MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class RugCheckError(RuntimeError):
    """Visible, typed failure at the RugCheck evidence boundary."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def validate_mint(mint: str) -> str:
    value = mint.strip()
    if not _MINT_RE.fullmatch(value):
        raise RugCheckError("invalid Solana mint", status_code=422)
    return value


async def get_token_report(mint: str) -> dict[str, Any]:
    """Fetch one exact-mint RugCheck report without persistence or LLM routing."""

    import httpx

    exact_mint = validate_mint(mint)
    url = RUGCHECK_REPORT_URL.format(mint=quote(exact_mint, safe=""))
    try:
        async with httpx.AsyncClient(timeout=RUGCHECK_TIMEOUT_SECONDS) as client:
            response = await client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status == 404:
            raise RugCheckError(
                "RugCheck report is not available", status_code=404
            ) from error
        if status == 429:
            raise RugCheckError("RugCheck is rate limited", status_code=503) from error
        raise RugCheckError(
            f"RugCheck request failed with status {status}", status_code=502
        ) from error
    except httpx.RequestError as error:
        timeout_type = getattr(httpx, "TimeoutException", None)
        if timeout_type is not None and isinstance(error, timeout_type):
            raise RugCheckError("RugCheck request timed out", status_code=504) from error
        raise RugCheckError("RugCheck request failed", status_code=502) from error

    try:
        report = response.json()
    except ValueError as error:
        raise RugCheckError("RugCheck returned invalid JSON", status_code=502) from error
    if not isinstance(report, dict):
        raise RugCheckError("RugCheck returned an invalid report", status_code=502)

    report_json = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    return {
        "source": "rugcheck",
        "mint": exact_mint,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "report_bytes": len(report_json.encode("utf-8")),
        "rough_report_tokens": (len(report_json) + 3) // 4,
        "report": report,
    }
