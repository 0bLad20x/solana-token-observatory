import json

import httpx

from jupiter_data_transform.jupiter import JupiterClient


async def test_client_batches_mints_and_rotates_keys() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        queried = request.url.params["query"].split(",")
        return httpx.Response(
            200,
            json=[{"id": mint, "usdPrice": 1.0} for mint in queried],
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://api.jup.ag",
        transport=transport,
    ) as http_client:
        client = JupiterClient(api_keys=["key-a", "key-b"], client=http_client)
        result = await client.fetch_tokens([f"mint-{index}" for index in range(101)])

    assert len(result) == 101
    assert len(calls) == 2
    assert calls[0].headers["x-api-key"] == "key-a"
    assert calls[1].headers["x-api-key"] == "key-b"
    assert len(calls[0].url.params["query"].split(",")) == 100
    assert len(calls[1].url.params["query"].split(",")) == 1
    assert json.loads(calls[0].content or b"null") is None
