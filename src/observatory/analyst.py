from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from .tools import (
    QueryToolError,
    TemporalToolError,
    query_capabilities,
    query_tokens,
    query_tokens_tool,
    temporal_context_tool,
    validate_temporal_context_arguments,
)

MISTRAL_CONVERSATIONS_URL = "https://api.mistral.ai/v1/conversations"
MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"
WEB_SEARCH_MODES = frozenset({"web_search", "web_search_premium"})
UNSUPPORTED_QUERY_ANSWER = (
    "This question cannot be mapped unambiguously to the current token data."
)
TEMPORAL_MAX_OUTPUT_TOKENS = 1800
logger = logging.getLogger(__name__)


class AnalystError(RuntimeError):
    """Visible, sanitized failure at the external analyst boundary."""


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


async def _post_json(
    *, client: Any, httpx: Any, url: str, api_key: str, request: dict[str, Any]
) -> dict[str, Any]:
    try:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=request,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        raise AnalystError(f"Mistral request failed with status {status}") from error
    except httpx.RequestError as error:
        raise AnalystError("Mistral request failed") from error

    try:
        payload = response.json()
    except ValueError as error:
        raise AnalystError("Mistral returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise AnalystError("Mistral returned an invalid response")
    return payload


def _chat_message(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AnalystError("Mistral returned no chat choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise AnalystError("Mistral returned no chat message")
    return message


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = [
        item["text"]
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
    ]
    return "".join(parts).strip()


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
from a deterministic temporal SUMMARY derived from the available observation window.
You MUST call get_token_temporal_context exactly once with the exact selected mint before
answering. Do not request another mint, SQL, hidden data, a custom range, or a resolution.

Selected token:
- Mint: {token['mint']}
- Name: {token.get('name') or 'unknown'}
- Symbol: {token.get('symbol') or 'unknown'}
- Launchpad: {token.get('launchpad') or 'unknown'}

Evidence semantics:
- The tool returns token identity plus a compact summary. It does NOT return time buckets.
- history.from/to/hours describe the actual covered observation window.
- market_cap, liquidity and holders can contain start/current/min/max/change_pct.
- market_cap may also contain peak_at and max_drawdown_pct.
- activity_1h fields are rolling one-hour source metrics. Their summary values are
  descriptive snapshots such as current and median; NEVER sum rolling values.
- Ratio summaries describe relationships between metrics. Interpret the direction
  mathematically; do not infer causality merely because a ratio changed.
- Missing means unknown, never zero. Do not invent proxies or unavailable chronology.
- Do NOT claim phases, turning points, exact event order, or historical values that are
  absent from the summary. In particular, current/median does not imply start/min/max.

Expert analysis requirements:
1. Establish the observation horizon and data quality/coverage limits first.
2. Diagnose valuation trajectory using market cap change, range, peak and drawdown.
3. Diagnose liquidity resilience relative to valuation, including liquidity/market-cap
   behavior where available.
4. Diagnose holder development and ownership concentration where available.
5. Compare CURRENT activity with its MEDIAN baseline: buy/sell pressure, trader activity,
   net flow and organic participation. Distinguish current conditions from the broader
   observed baseline.
6. Look for cross-metric confirmation or divergence. Examples: valuation falling while
   holders rise; liquidity holding while market cap falls; current buy pressure improving
   despite a weak full-window trajectory. Explain why such combinations matter.
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
    context_loader: Callable[[str], dict[str, Any] | None],
) -> dict[str, Any]:
    """Execute one selected-mint summary tool call and return an expert diagnosis."""

    import httpx

    selected_mint = token["mint"]
    messages = [
        {"role": "system", "content": _temporal_instructions(token)},
        {"role": "user", "content": question},
    ]
    request = {
        "model": model,
        "messages": messages,
        "tools": [temporal_context_tool(selected_mint)],
        "tool_choice": "required",
        "parallel_tool_calls": False,
        "temperature": 0,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        first_payload = await _post_json(
            client=client,
            httpx=httpx,
            url=MISTRAL_CHAT_URL,
            api_key=api_key,
            request=request,
        )
        first_message = _chat_message(first_payload)
        call = _tool_call(first_message, "get_token_temporal_context")
        if call is None:
            raise AnalystError("Mistral did not request temporal summary evidence")

        call_id, arguments = call
        try:
            mint = validate_temporal_context_arguments(arguments, selected_mint)
        except TemporalToolError as error:
            raise AnalystError(
                f"Invalid get_token_temporal_context arguments: {error}"
            ) from error

        context = await asyncio.to_thread(context_loader, mint)
        if context is None:
            raise AnalystError("No temporal summary is available for the selected mint")

        assistant_message = {
            "role": "assistant",
            "content": first_message.get("content") or "",
            "tool_calls": first_message["tool_calls"],
        }
        context_json = json.dumps(
            context,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        context_bytes = len(context_json.encode("utf-8"))
        rough_tokens = (len(context_json) + 3) // 4
        final_request = {
            "model": model,
            "messages": [
                *messages,
                assistant_message,
                {
                    "role": "tool",
                    "name": "get_token_temporal_context",
                    "tool_call_id": call_id,
                    "content": context_json,
                },
            ],
            "temperature": 0,
            "max_tokens": TEMPORAL_MAX_OUTPUT_TOKENS,
        }
        final_started = perf_counter()
        logger.info(
            "[temporal] final_mistral_start mint=%s model=%s bytes=%s rough_tokens=%s max_tokens=%s",
            mint,
            model,
            context_bytes,
            rough_tokens,
            TEMPORAL_MAX_OUTPUT_TOKENS,
        )
        try:
            final_payload = await _post_json(
                client=client,
                httpx=httpx,
                url=MISTRAL_CHAT_URL,
                api_key=api_key,
                request=final_request,
            )
        except AnalystError:
            logger.warning(
                "[temporal] final_mistral_failed mint=%s elapsed=%.2fs",
                mint,
                perf_counter() - final_started,
            )
            raise
        logger.info(
            "[temporal] final_mistral_done mint=%s elapsed=%.2fs",
            mint,
            perf_counter() - final_started,
        )

    answer = _message_text(_chat_message(final_payload))
    if not answer:
        raise AnalystError(
            "Mistral returned no answer after get_token_temporal_context"
        )

    history_meta = context["summary"]["history"]
    return {
        "answer": answer,
        "scope": "temporal",
        "tool": {
            "name": "get_token_temporal_context",
            "evidence": "summary_only",
            "mint": mint,
            "from": history_meta["from"],
            "to": history_meta["to"],
            "history_hours": history_meta["hours"],
            "observations": history_meta["observations"],
            "rough_input_tokens": rough_tokens,
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
