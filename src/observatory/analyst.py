from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

MISTRAL_CONVERSATIONS_URL = "https://api.mistral.ai/v1/conversations"
WEB_SEARCH_MODES = frozenset({"web_search", "web_search_premium"})


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

    return {"answer": answer, "sources": sources, "search_mode": search_mode}


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

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                MISTRAL_CONVERSATIONS_URL,
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
    return _parse_response(payload, mode)
