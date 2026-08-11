from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from .tools import QUERY_FIELDS, QUERY_TOKENS_TOOL, QueryToolError, query_tokens

MISTRAL_CONVERSATIONS_URL = "https://api.mistral.ai/v1/conversations"
MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"
WEB_SEARCH_MODES = frozenset({"web_search", "web_search_premium"})
UNSUPPORTED_QUERY_ANSWER = (
    "This question cannot be answered from the current token projection. "
    f"Available current fields are: {', '.join(QUERY_FIELDS)}."
)


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


def _tool_call(message: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    calls = message.get("tool_calls")
    if not calls:
        return None
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
        raise AnalystError("Mistral must request exactly one query_tokens call")

    call = calls[0]
    function = call.get("function")
    call_id = call.get("id")
    if (
        not isinstance(function, dict)
        or function.get("name") != "query_tokens"
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


def _internal_instructions() -> str:
    return f"""Answer questions about the current active Solana token population.
For any question that is exactly answerable from the available current fields, call
query_tokens once and answer only from its result. Available fields: {', '.join(QUERY_FIELDS)}.
The tool has no price-change field, historical series, social data or inferred metrics.
Never substitute a different field or time window. If the requested information is not
available, do not call the tool and say that the current projection cannot answer it.
Missing values are unknown, not zero. Keep the final answer concise and name the metric.
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

    messages = [
        {"role": "system", "content": _internal_instructions()},
        {"role": "user", "content": question},
    ]
    request = {
        "model": model,
        "messages": messages,
        "tools": [QUERY_TOKENS_TOOL],
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
