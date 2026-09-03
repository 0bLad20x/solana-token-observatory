from typing import Any

MISTRAL_CONVERSATIONS_URL = "https://api.mistral.ai/v1/conversations"
MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"
MAX_PROVIDER_ERROR_TEXT = 500


class AnalystError(RuntimeError):
    """Visible, sanitized failure at the external analyst boundary."""


def _safe_error_scalar(value: Any, *, limit: int = MAX_PROVIDER_ERROR_TEXT) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    return text[:limit]


def _provider_error_fields(response: Any, api_key: str) -> dict[str, str]:
    """Extract only bounded provider error metadata safe for diagnostics.

    Request bodies, prompts, headers and arbitrary response structures are never
    surfaced. If the provider unexpectedly echoes the active API key inside one
    of the accepted scalar fields, it is redacted before returning the message.
    """

    try:
        payload = response.json()
    except (AttributeError, ValueError):
        return {}

    if not isinstance(payload, dict):
        return {}

    candidate = payload
    detail = payload.get("detail")
    if isinstance(detail, dict):
        candidate = detail

    result: dict[str, str] = {}
    for key in ("code", "type", "param", "message"):
        value = _safe_error_scalar(candidate.get(key))
        if value is None:
            continue
        if api_key:
            value = value.replace(api_key, "[redacted]")
        result[key] = value

    if "message" not in result:
        detail_text = _safe_error_scalar(detail)
        if detail_text is not None:
            if api_key:
                detail_text = detail_text.replace(api_key, "[redacted]")
            result["message"] = detail_text

    return result


def _http_error_message(response: Any, api_key: str) -> str:
    status = getattr(response, "status_code", "unknown")
    fields = _provider_error_fields(response, api_key)
    if not fields:
        return f"Mistral request failed with status {status}"

    details = " ".join(
        f"{key}={value}"
        for key, value in fields.items()
    )
    return f"Mistral request failed with status {status}: {details}"


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
        raise AnalystError(
            _http_error_message(error.response, api_key)
        ) from error
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
