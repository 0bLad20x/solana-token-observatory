from __future__ import annotations

import json
import logging
from time import perf_counter
from typing import Any

from .mistral import (
    AnalystError,
    MISTRAL_CHAT_URL,
    chat_message,
    message_text,
    post_json,
)
from .rugcheck_projection import project_rugcheck_evidence

RUGCHECK_MAX_OUTPUT_TOKENS = 1600
RUGCHECK_REQUEST_TIMEOUT_SECONDS = 45.0
logger = logging.getLogger(__name__)


def _instructions(token: dict[str, Any]) -> str:
    return f"""Act as a senior Solana token safety analyst. Analyze exactly one selected token
using only the RugCheck safety metadata supplied with the user request.

Selected token:
- Mint: {token['mint']}
- Name: {token.get('name') or 'unknown'}
- Symbol: {token.get('symbol') or 'unknown'}
- Launchpad: {token.get('launchpad') or 'unknown'}

Evidence rules:
- RugCheck is an external provider, not Jupiter system truth.
- Treat fetched_at as the observation time of this external report.
- Missing means unknown, never safe.
- The delivered JSON is a deterministic metadata projection of the raw RugCheck report.
  The complete provider report remains available through the direct evidence endpoint.
- The supplied semantics are authoritative for interpreting every delivered metric. Use
  them directly; do not invent score formulas, score direction, probability meanings,
  category thresholds or alternative metric definitions.
- Never classify raw score or score_normalised numerically as low/high risk, a safety
  rating, or a percentage unless RugCheck explicitly supplied such a category as a risk.
- Each risk name/level/value/score/description is RugCheck provider evidence. Use the
  provider description as its meaning. Do not add unstated consequences or causal claims
  as though RugCheck reported them; label any additional inference explicitly.
- detected_at is RugCheck detection time, not token creation time or token age.
- launchpad and deploy_platform are identifiers only. Do not assign a platform reputation,
  general scam/rug frequency or risk unless RugCheck supplied an explicit risk saying so.
- Wallet addresses, individual top-holder rows, individual market rows and repeated raw
  account snapshots are intentionally not sent to you. Their relevant measurable
  properties are represented as deterministic aggregates.
- topN_pct can include RugCheck-labelled AMM/pool infrastructure. Do not equate raw top
  holder concentration with beneficial-owner centralization. Use the known-account
  percentage aggregates when discussing infrastructure versus unlabelled holders.
- graph-level insider signals are independent from top-holder insider flags. Do not infer
  whether they overlap unless evidence explicitly establishes that relation.
- Market counts, market-type counts, liquidity concentration and LP-lock counts are
  deterministic aggregates. A positive lpLockedPct and locker_count/locker_scan_status are
  separate provider facts. Do not infer that missing/no locker entries mean liquidity can
  be withdrawn, and do not call those fields contradictory without explicit evidence.
- Transfer-fee fields are provider facts only. Do not infer future fee configurability from
  authority presence or maxAmount unless provider evidence explicitly states it.
- rugged=false means RugCheck did not mark the token rugged in this observation; it is not
  proof of safety or future behavior.
- Do not invent ownership identities, creator intent, lock mechanisms or market behavior
  beyond the delivered metadata.
- Distinguish RugCheck facts from your inference.
- Do not create a new deterministic good/bad score and do not make lifecycle, trading or
  deactivation decisions.

Prioritize the user's question. Focus on the highest-information safety properties:
explicit provider risks, token control, metadata mutability, holder-row concentration,
known infrastructure share, insider signals, creator concentration, liquidity concentration
and LP-lock evidence. Explain material unknowns without converting them into negative facts.
End with a calibrated evidence assessment, not a guaranteed verdict.
"""


async def analyze_rugcheck_report(
    *,
    api_key: str,
    model: str,
    token: dict[str, Any],
    question: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Interpret deterministic RugCheck safety metadata with one strong-model request."""

    import httpx

    analysis_evidence = project_rugcheck_evidence(evidence)
    projection = analysis_evidence.get("projection", {})
    llm_evidence = {
        "source": analysis_evidence.get("source", "rugcheck"),
        "fetched_at": analysis_evidence.get("fetched_at"),
        "summary": analysis_evidence.get("summary"),
    }
    context_json = json.dumps(llm_evidence, ensure_ascii=False, separators=(",", ":"))
    context_bytes = len(context_json.encode("utf-8"))
    rough_context_tokens = (context_bytes + 3) // 4

    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": _instructions(token)},
            {
                "role": "user",
                "content": (
                    f"User question:\n{question}\n\n"
                    f"RugCheck external safety metadata JSON:\n{context_json}"
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
    async with httpx.AsyncClient(timeout=RUGCHECK_REQUEST_TIMEOUT_SECONDS) as client:
        payload = await post_json(
            client=client,
            httpx=httpx,
            url=MISTRAL_CHAT_URL,
            api_key=api_key,
            request=request,
        )

    logger.warning(
        "[rugcheck] mistral_done mint=%s elapsed=%.2fs",
        evidence.get("mint"),
        perf_counter() - started,
    )
    answer = message_text(chat_message(payload))
    if not answer:
        raise AnalystError("Mistral returned no RugCheck answer")

    return {
        "answer": answer,
        "scope": "rugcheck",
        "evidence": {
            "type": "rugcheck_token_report",
            "mode": projection.get("type", "rugcheck_analysis_v4"),
            "source": "rugcheck",
            "mint": evidence["mint"],
            "fetched_at": evidence["fetched_at"],
            "raw_report_bytes": projection.get("raw_report_bytes"),
            "raw_rough_report_tokens": projection.get("raw_rough_report_tokens"),
            "analysis_context_bytes": context_bytes,
            "analysis_rough_tokens": rough_context_tokens,
            "markets_observed": projection.get("markets_observed"),
            "top_holders_observed": projection.get("top_holders_observed"),
            "known_accounts_observed": projection.get("known_accounts_observed"),
            "wallet_addresses_sent_to_llm": projection.get(
                "wallet_addresses_sent_to_llm"
            ),
        },
    }
