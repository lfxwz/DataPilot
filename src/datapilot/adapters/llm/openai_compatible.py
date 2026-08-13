"""Minimal OpenAI-compatible client with bounded retries and JSON output."""

import json
from time import sleep
from typing import Any

import httpx
from pydantic import SecretStr

from datapilot.adapters.llm.errors import LLMProviderError, LLMResponseValidationError
from datapilot.domain.llm import LLMUsage, StructuredCompletion


class OpenAICompatibleClient:
    """Call a configured Chat Completions endpoint without exposing credentials."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr,
        model: str,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        thinking_enabled: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("LLM base_url must use HTTPS")
        if not model.strip():
            raise ValueError("model must not be empty")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")

        self._model = model
        self._max_retries = max_retries
        self._thinking_enabled = thinking_enabled
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
    ) -> StructuredCompletion:
        """Return a JSON object from an OpenAI-compatible chat endpoint."""

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        payload = {
            "model": self._model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": False,
            "thinking": {"type": "enabled" if self._thinking_enabled else "disabled"},
        }

        last_error: Exception | None = None
        for format_attempt in range(self._max_retries + 1):
            response = self._post_with_retry(payload)
            try:
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                parsed_content = self._parse_json_object(content)
                usage = body.get("usage") or {}
                return StructuredCompletion(
                    model=str(body.get("model") or self._model),
                    data=parsed_content,
                    usage=LLMUsage(
                        prompt_tokens=int(usage.get("prompt_tokens", 0)),
                        completion_tokens=int(usage.get("completion_tokens", 0)),
                        total_tokens=int(usage.get("total_tokens", 0)),
                    ),
                    provider_request_id=response.headers.get("x-request-id"),
                )
            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                if format_attempt < self._max_retries:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "The previous response was empty or invalid JSON. "
                                "Return exactly one complete JSON object matching the requested "
                                "schema, with no Markdown."
                            ),
                        }
                    )

        raise LLMResponseValidationError(
            "The LLM provider returned an invalid structured response after bounded retries."
        ) from last_error

    @staticmethod
    def _parse_json_object(content: object) -> dict[str, Any]:
        if not isinstance(content, str) or not content.strip():
            raise TypeError("structured output content must be a non-empty string")
        candidate = content.strip()
        if candidate.startswith("```") and candidate.endswith("```"):
            lines = candidate.splitlines()
            if len(lines) >= 3:
                candidate = "\n".join(lines[1:-1]).strip()
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            raise TypeError("structured output must be a JSON object")
        return parsed

    def _post_with_retry(self, payload: dict[str, Any]) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post("/chat/completions", json=payload)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise LLMProviderError("The LLM provider is unavailable.") from exc
                sleep(min(0.25 * (2**attempt), 2.0))
                continue

            if response.status_code < 400:
                return response
            if response.status_code not in {408, 429, 500, 502, 503, 504}:
                raise LLMProviderError(
                    f"The LLM provider rejected the request with status {response.status_code}."
                )
            if attempt == self._max_retries:
                raise LLMProviderError(
                    "The LLM provider remained unavailable after bounded retries."
                )
            sleep(min(0.25 * (2**attempt), 2.0))

        raise AssertionError("unreachable")
