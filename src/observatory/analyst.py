import asyncio
import json
import logging
from collections.abc import Callable
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from .mistral import (
    AnalystError,
    MISTRAL_CHAT_URL,
    MISTRAL_CONVERSATIONS_URL,
    chat_message as _chat_message,
    message_text as _message_text,
    post_json as _post_json,
)
from .tools import (
    QueryToolError,
    query_capabilities,
    query_tokens,
    query_tokens_tool,
)

WEB_SEARCH_MODES = frozenset({"web_search", "web_search_premium"})
UNSUPPORTED_QUERY_ANSWER = (
    "This question cannot be mapped unambiguously to the current token data."
)
TEMPORAL_MAX_OUTPUT_TOKENS = 1800
TEMPORAL_REQUEST_TIMEOUT_SECONDS = 45.0
logger = logging.getLogger(__name__)


def validate_search_mode(value: str) -> str:
    mode = value.strip().lower()
    if mode not in WEB_SEARCH_MODES:
        allowed = ", ".join(sorted(WEB_SEARCH_MODES))
        raise ValueError(f"MISTRAL_WEB_SEARCH_MODE must be one of: {allowed}")
    return mode


def _prompt(token: dict[str, Any], question: str) -> str:
    return f"""Research exactly one Solana token.
Always execute the available web search tool before answering.
Use the exact mint address as the primary identity. Name and symbol are hints only.
Do not attribute a website, social account, project, or claim to this token unless the
web evidence connects it to the exact mint. If reliable evidence is unavailable, say so.
Keep external evidence separate from inference and answer concisely.

Selected token:
- Mint: {token['mint']}
- Name: {token.get('name') or 'unknown'}
- Symbol: {token.get('symbol') or 'unknown'}
- Launchpad: {token.get('launchpad') or 'unknown'}

User question: {question}
"""


def _parse_response(payload: dict[str, Any], search_mode: str) -> dict[str, Any]:
    outputs = payload.get("outputs")
    if not isinstance(outputs, list):
        raise AnalystError("Mistral returned no conversation outputs")

    tool_used = any(
        output.get("type") == "tool.execution"
        and output.get("name") in WEB_SEARCH_MODES
        for output in outputs
        if isinstance(output, dict)
    )
    if not tool_used:
        raise AnalystError("Mistral did not execute web search")

    answer_parts: list[str] = []
    sources: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for output in outputs:
        if not isinstance(output, dict) or output.get("type") != "message.output":
            continue
        content = output.get("content")
        if isinstance(content, str):
            answer_parts.append(content)
            continue
        if not isinstance(content, list):
            continue

        for chunk in content:
            if not isinstance(chunk, dict):
                continue
            if chunk.get("type") == "text" and isinstance(chunk.get("text"), str):
                answer_parts.append(chunk["text"])
                continue
            if chunk.get("type") != "tool_reference":
                continue
            url = chunk.get("url")
            if not isinstance(url, str) or url in seen_urls:
                continue
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            seen_urls.add(url)
            title = chunk.get("title")
            source_title = title if isinstance(title, str) and title else url
            sources.append({"title": source_title, "url": url})

    answer = "".join(answer_parts).strip()
    if not answer:
        raise AnalystError("Mistral returned no answer")

    return {
        "answer": answer,
        "scope": "web",
        "sources": sources,
        "search_mode": search_mode,
    }


def _tool_call(
    message: dict[str, Any],
    expected_name: str = "query_tokens",
) -> tuple[str, dict[str, Any]] | None:
    calls = message.get("tool_calls")
    if not calls:
        return None
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
        raise AnalystError(f"Mistral must request exactly one {expected_name} call")

    call = calls[0]
    function = call.get("function")
    call_id = call.get("id")
    if (
        not isinstance(function, dict)
        or function.get("name") != expected_name
        or not isinstance(call_id, str)
        or not call_id
    ):
        raise AnalystError("Mistral requested an unsupported tool")

    raw_arguments = function.get("arguments")
    try:
        arguments = (
            json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        )
    except json.JSONDecodeError as error:
        raise AnalystError("Mistral returned invalid tool arguments") from error
    if not isinstance(arguments, dict):
        raise AnalystError("Mistral returned invalid tool arguments")
    return call_id, arguments


def _internal_instructions(capabilities: dict[str, Any]) -> str:
    vocabulary = json.dumps(capabilities, ensure_ascii=False, separators=(",", ":"))
    return f"""Answer questions about the current active Solana token population.
Use the vocabulary below to translate natural language into canonical query_tokens
arguments. Interpret clear spelling, spacing, punctuation and language variations, but
emit only a listed field key, sort-order key and launchpad value. For a clear supported
question, call query_tokens exactly once and answer only from its result. If a required
dimension is absent or the intent remains ambiguous, do not call the tool. Never replace
an unavailable metric or time window with another one. Missing values are unknown, not
zero. Keep the final answer concise and name the metric.

Current query vocabulary:
{vocabulary}
"""


def _temporal_instructions(token: dict[str, Any]) -> str:
    return f"""Act as a senior Solana token-market analyst. Analyze exactly one selected token
from the deterministic temporal SUMMARY supplied with the user request. The Summary is
derived from the available retained observation window; no raw history or time buckets
are available to you.

Selected token:
- Mint: {token['mint']}
- Name: {token.get('name') or 'unknown'}
- Symbol: {token.get('symbol') or 'unknown'}
- Launchpad: {token.get('launchpad') or 'unknown'}

Evidence semantics:
- history.from/to/hours describe the actual covered observation window, not token age.
- Observation count does not prove continuous coverage or absence of gaps.
- market_cap, liquidity and holders can contain start/current/min/max/change_pct.
- market_cap peak_at and max refer only to the delivered observation window, never an ATH.
- max_drawdown_pct does not prove that every individual hour was positive or negative.
- activity_1h fields are rolling one-hour source metrics. Their Summary values are
  descriptive snapshots such as current and median; NEVER sum rolling values.
- Ratio summaries describe relationships between metrics. Interpret their direction
  mathematically; do not infer causality merely because a ratio changed.
- Missing means unknown, never zero. Do not invent proxies or unavailable chronology.
- Do NOT claim linear, parabolic, smooth or phased growth, turning points, exact event
  order, or historical values that are absent from the Summary.
- Do NOT infer fake volume, wash trading, bots, whales, manipulation, accumulation,
  distribution or coordinated behavior from aggregate metrics alone.
- A lower but still positive num_net_buyers value is weaker positive net buying, not
  outflow. A change in top_holders_pct is concentration change only; actor identity and
  mechanism are unknown. A change in dev_balance_pct is balance change only.
- Do not use overbought, oversold, support, resistance, breakout or similar technical-
  analysis labels unless directly supported by delivered evidence.
- Percentage change and multiplicative growth are different: use final/start for an x-fold
  statement and change_pct for the percentage increase.

Expert analysis requirements:
1. Establish the observation horizon and evidence limitations first.
2. Diagnose valuation trajectory using market cap change, range, peak and drawdown.
3. Diagnose liquidity resilience relative to valuation, including liquidity/market-cap
   behavior where available.
4. Diagnose holder development and ownership concentration where available.
5. Compare CURRENT activity with its MEDIAN baseline: buy/sell pressure, trader activity,
   net flow and organic participation. Distinguish current conditions from the broader
   observed baseline.
6. Look for cross-metric confirmation or divergence. Explain relationships without
   inventing causality or chronology.
7. Identify the strongest constructive signals, strongest risk signals, and material
   unknowns. Do not manufacture a deterministic good/bad score.
8. End with a calibrated expert assessment for the user's question: constructive,
   neutral/mixed, weak, or high-risk, plus confidence and the evidence that most affects
   that assessment.

Be analytical rather than descriptive. Do not merely restate every field. Prefer a small
number of high-value relationships and explicitly separate measured facts from inference.
"""


async def query_current_tokens(
    *,
    api_key: str,
    model: str,
    tokens: list[dict[str, Any]],
    question: str,
) -> dict[str, Any]:
    """Let Mistral translate one question into one bounded read-only token query."""

    import httpx

    capabilities = query_capabilities(tokens)
    messages = [
        {"role": "system", "content": _internal_instructions(capabilities)},
        {"role": "user", "content": question},
    ]
    request = {
        "model": model,
        "messages": messages,
        "tools": [query_tokens_tool(capabilities)],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "temperature": 0,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        first_payload = await _post_json(
            client=client,
            httpx=httpx,
            url=MISTRAL_CHAT_URL,
            api_key=api_key,
            request=request,
        )
        first_message = _chat_message(first_payload)
        call = _tool_call(first_message)
        if call is None:
            return {
                "answer": UNSUPPORTED_QUERY_ANSWER,
                "scope": "current_data",
                "tool": None,
                "capabilities": capabilities,
            }

        call_id, arguments = call
        try:
            result = query_tokens(tokens, arguments)
        except QueryToolError as error:
            raise AnalystError(f"Invalid query_tokens arguments: {error}") from error

        assistant_message = {
            "role": "assistant",
            "content": first_message.get("content") or "",
            "tool_calls": first_message["tool_calls"],
        }
        final_request = {
            "model": model,
            "messages": [
                *messages,
                assistant_message,
                {
                    "role": "tool",
                    "name": "query_tokens",
                    "tool_call_id": call_id,
                    "content": json.dumps(result, separators=(",", ":")),
                },
            ],
            "temperature": 0,
        }
        final_payload = await _post_json(
            client=client,
            httpx=httpx,
            url=MISTRAL_CHAT_URL,
            api_key=api_key,
            request=final_request,
        )

    answer = _message_text(_chat_message(final_payload))
    if not answer:
        raise AnalystError("Mistral returned no answer after query_tokens")
    return {
        "answer": answer,
        "scope": "current_data",
        "tool": {
            "name": "query_tokens",
            "arguments": result["query"],
            "matched_count": result["matched_count"],
            "returned_count": result["returned_count"],
            "tokens": result["tokens"],
        },
    }


async def analyze_temporal_token(
    *,
    api_key: str,
    model: str,
    token: dict[str, Any],
    question: str,
    summary_loader: Callable[[str], dict[str, Any] | None],
) -> dict[str, Any]:
    """Load one selected-token Summary and answer with one Mistral request."""

    import httpx

    mint = token["mint"]
    summary = await asyncio.to_thread(summary_loader, mint)
    if summary is None:
        raise AnalystError("No temporal summary is available for the selected mint")

    identity = {"mint": mint}
    for key in ("name", "symbol", "launchpad"):
        value = token.get(key)
        if value not in (None, ""):
            identity[key] = value
    context = {"token": identity, "summary": summary}
    context_json = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    context_bytes = len(context_json.encode("utf-8"))
    rough_summary_tokens = (len(context_json) + 3) // 4

    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": _temporal_instructions(token)},
            {
                "role": "user",
                "content": (
                    f"User question:\n{question}\n\n"
                    f"Deterministic temporal evidence JSON:\n{context_json}"
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": TEMPORAL_MAX_OUTPUT_TOKENS,
    }

    started = perf_counter()
    logger.warning(
        "[temporal] mistral_start mint=%s model=%s bytes=%s rough_summary_tokens=%s max_tokens=%s",
        mint,
        model,
        context_bytes,
        rough_summary_tokens,
        TEMPORAL_MAX_OUTPUT_TOKENS,
    )
    try:
        async with httpx.AsyncClient(timeout=TEMPORAL_REQUEST_TIMEOUT_SECONDS) as client:
            payload = await _post_json(
                client=client,
                httpx=httpx,
                url=MISTRAL_CHAT_URL,
                api_key=api_key,
                request=request,
            )
    except AnalystError:
        logger.warning(
            "[temporal] mistral_failed mint=%s elapsed=%.2fs",
            mint,
            perf_counter() - started,
        )
        raise
    logger.warning(
        "[temporal] mistral_done mint=%s elapsed=%.2fs",
        mint,
        perf_counter() - started,
    )

    answer = _message_text(_chat_message(payload))
    if not answer:
        raise AnalystError("Mistral returned no temporal summary answer")

    history_meta = summary["history"]
    return {
        "answer": answer,
        "scope": "temporal",
        "evidence": {
            "type": "temporal_summary",
            "mint": mint,
            "from": history_meta["from"],
            "to": history_meta["to"],
            "history_hours": history_meta["hours"],
            "observations": history_meta["observations"],
            "rough_summary_tokens": rough_summary_tokens,
        },
    }


async def research_token(
    *,
    api_key: str,
    model: str,
    search_mode: str,
    token: dict[str, Any],
    question: str,
) -> dict[str, Any]:
    import httpx

    mode = validate_search_mode(search_mode)
    request = {
        "model": model,
        "inputs": [{"role": "user", "content": _prompt(token, question)}],
        "tools": [{"type": mode}],
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        payload = await _post_json(
            client=client,
            httpx=httpx,
            url=MISTRAL_CONVERSATIONS_URL,
            api_key=api_key,
            request=request,
        )
    return _parse_response(payload, mode)
