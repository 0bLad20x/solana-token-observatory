from __future__ import annotations

import json
import logging
from time import perf_counter
from typing import Any

from .analyst import AnalystError, MISTRAL_CHAT_URL
from .rugcheck_projection import project_rugcheck_evidence

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
- Use only fields actually present in the delivered evidence. Missing means unknown,
  never safe.
- The input contains a deterministic transport projection for LLM analysis. The raw
  RugCheck report remains available through the direct evidence endpoint.
- Every market remains represented, but repeated raw mint/vault account snapshots are
  intentionally omitted. Do not treat omitted account-level fields as provider absence.
- knownAccounts contains only provider labels for addresses referenced elsewhere outside
  the market rows; it is not the provider's full known-account registry.
- RugCheck risks, score, score_normalised and rugged are provider evidence, not an
  internally verified safety verdict.
- Do not invent ownership identities, creator intent, lock state, authorities or market
  structure when the delivered evidence does not provide them.
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
    """Interpret one RugCheck report through one bounded strong-model request."""

    import httpx

    analysis_evidence = project_rugcheck_evidence(evidence)
    context_json = json.dumps(
        analysis_evidence, ensure_ascii=False, separators=(",", ":")
    )
    context_bytes = len(context_json.encode("utf-8"))
    rough_context_tokens = (context_bytes + 3) // 4
    projection = analysis_evidence.get("projection", {})

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
        "[rugcheck] mistral_start mint=%s model=%s raw_bytes=%s analysis_bytes=%s "
        "rough_analysis_tokens=%s",
        evidence.get("mint"),
        model,
        projection.get("raw_report_bytes"),
        context_bytes,
        rough_context_tokens,
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
            "mode": projection.get("type", "rugcheck_analysis_v1"),
            "source": "rugcheck",
            "mint": evidence["mint"],
            "fetched_at": evidence["fetched_at"],
            "raw_report_bytes": projection.get("raw_report_bytes"),
            "raw_rough_report_tokens": projection.get("raw_rough_report_tokens"),
            "analysis_context_bytes": context_bytes,
            "analysis_rough_tokens": rough_context_tokens,
            "markets_total": projection.get("markets_total"),
            "known_accounts_total": projection.get("known_accounts_total"),
            "known_accounts_retained": projection.get("known_accounts_retained"),
        },
    }
