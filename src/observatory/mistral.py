from __future__ import annotations

from typing import Any

MISTRAL_CONVERSATIONS_URL = "https://api.mistral.ai/v1/conversations"
MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"


class AnalystError(RuntimeError):
    """Visible, sanitized failure at the external analyst boundary."""


async def post_json(
    *,
    client: Any,
    httpx: Any,
    url: str,
    api_key: str,
    request: dict[str, Any],
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
    return payload


def chat_message(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AnalystError("Mistral returned no chat choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise AnalystError("Mistral returned no chat message")
    return message


def message_text(message: dict[str, Any]) -> str:
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
