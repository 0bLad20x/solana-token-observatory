from __future__ import annotations

import json
import logging
from time import perf_counter
from typing import Any

from .analyst import AnalystError, MISTRAL_CHAT_URL

RUGCHECK_MAX_OUTPUT_TOKENS = 1600
RUGCHECK_REQUEST_TIMEOUT_SECONDS = 45.0
logger = logging.getLogger(__name__)


def _instructions(token: dict[str, Any]) -> str:
    return f"""Act as a senior Solana token safety analyst. Analyze exactly one selected token
using only the RugCheck evidence supplied with the user request.

Selected token:
- Mint: {token['mint']}
- Name: {token.get('name') or 'unknown'}
- Symbol: {token.get('symbol') or 'unknown'}
- Launchpad: {token.get('launchpad') or 'unknown'}

Evidence rules:
- RugCheck is an external provider, not Jupiter system truth.
- Treat the fetched_at timestamp as the observation time of this external report.
- Use only fields actually present in the report. Missing means unknown, never safe.
- RugCheck risks, score, score_normalised and rugged are provider evidence, not an
  internally verified safety verdict.
- Do not invent ownership identities, creator intent, lock state, authorities or market
  structure when the report does not provide them.
- Distinguish facts reported by RugCheck from your inference.
- Do not convert the report into a new deterministic good/bad score.
- Do not make lifecycle, trading or deactivation decisions.

Prioritize the user's question. When relevant, examine authorities, metadata mutability,
listed risks, holder concentration/insider flags, creator history, market/liquidity and LP
lock evidence. Explain material unknowns and contradictions. End with a calibrated safety
evidence assessment and confidence, not a guarantee that the token is safe or unsafe.
"""


def _message_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AnalystError("Mistral returned no RugCheck chat choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise AnalystError("Mistral returned no RugCheck chat message")
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "".join(
        item["text"]
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
    ).strip()


async def analyze_rugcheck_report(
    *,
    api_key: str,
    model: str,
    token: dict[str, Any],
    question: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Interpret one already-fetched RugCheck report with one strong-model request."""

    import httpx

    context_json = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
    context_bytes = len(context_json.encode("utf-8"))
    rough_report_tokens = (len(context_json) + 3) // 4
    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": _instructions(token)},
            {
                "role": "user",
                "content": (
                    f"User question:\n{question}\n\n"
                    f"RugCheck external evidence JSON:\n{context_json}"
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": RUGCHECK_MAX_OUTPUT_TOKENS,
    }

    started = perf_counter()
    logger.warning(
        "[rugcheck] mistral_start mint=%s model=%s bytes=%s rough_report_tokens=%s",
        evidence.get("mint"),
        model,
        context_bytes,
        rough_report_tokens,
    )
    try:
        async with httpx.AsyncClient(timeout=RUGCHECK_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                MISTRAL_CHAT_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json=request,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        raise AnalystError(f"Mistral request failed with status {status}") from error
    except httpx.RequestError as error:
        timeout_type = getattr(httpx, "TimeoutException", None)
        if timeout_type is not None and isinstance(error, timeout_type):
            raise AnalystError("Mistral request timed out") from error
        raise AnalystError("Mistral request failed") from error

    try:
        payload = response.json()
    except ValueError as error:
        raise AnalystError("Mistral returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise AnalystError("Mistral returned an invalid response")

    logger.warning(
        "[rugcheck] mistral_done mint=%s elapsed=%.2fs",
        evidence.get("mint"),
        perf_counter() - started,
    )
    answer = _message_text(payload)
    if not answer:
        raise AnalystError("Mistral returned no RugCheck answer")

    return {
        "answer": answer,
        "scope": "rugcheck",
        "evidence": {
            "type": "rugcheck_token_report",
            "source": "rugcheck",
            "mint": evidence["mint"],
            "fetched_at": evidence["fetched_at"],
            "report_bytes": context_bytes,
            "rough_report_tokens": rough_report_tokens,
        },
    }
