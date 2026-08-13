"""Contract tests for the OpenAI-compatible provider adapter."""

import json

import httpx
import pytest
from pydantic import SecretStr

from datapilot.adapters.llm.errors import LLMResponseValidationError
from datapilot.adapters.llm.openai_compatible import OpenAICompatibleClient


def test_structured_completion_parses_json_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("Bearer ")
        assert json.loads(request.content)["thinking"] == {"type": "disabled"}
        return httpx.Response(
            200,
            headers={"x-request-id": "provider-request-1"},
            json={
                "model": "deepseek-v4-flash",
                "choices": [{"message": {"content": json.dumps({"objective": "analyze"})}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )

    client = OpenAICompatibleClient(
        base_url="https://api.deepseek.com",
        api_key=SecretStr("not-a-real-key"),
        model="deepseek-v4-flash",
        transport=httpx.MockTransport(handler),
    )
    try:
        completion = client.complete_json(system_prompt="system", user_prompt="user")
    finally:
        client.close()

    assert completion.data == {"objective": "analyze"}
    assert completion.usage.total_tokens == 15
    assert completion.provider_request_id == "provider-request-1"


def test_invalid_json_response_is_rejected() -> None:
    calls = 0

    def invalid_handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    client = OpenAICompatibleClient(
        base_url="https://api.deepseek.com",
        api_key=SecretStr("not-a-real-key"),
        model="deepseek-v4-flash",
        max_retries=2,
        transport=httpx.MockTransport(invalid_handler),
    )
    try:
        with pytest.raises(LLMResponseValidationError):
            client.complete_json(system_prompt="system", user_prompt="user")
    finally:
        client.close()
    assert calls == 3


def test_markdown_wrapped_json_is_normalized() -> None:
    client = OpenAICompatibleClient(
        base_url="https://api.deepseek.com",
        api_key=SecretStr("not-a-real-key"),
        model="deepseek-v4-flash",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"choices": [{"message": {"content": '```json\n{"ok": true}\n```'}}]},
            )
        ),
    )
    try:
        completion = client.complete_json(system_prompt="system", user_prompt="user")
    finally:
        client.close()

    assert completion.data == {"ok": True}


def test_plain_http_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        OpenAICompatibleClient(
            base_url="http://api.example.test",
            api_key=SecretStr("not-a-real-key"),
            model="model",
        )
