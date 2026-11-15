"""LLM ports, deterministic fake, and optional OpenAI-compatible client."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from repopilot.core.errors import (
    ExternalServiceUnavailableError,
    SchemaValidationError,
    ToolExecutionError,
)

OutputT = TypeVar("OutputT", bound=BaseModel)


@dataclass(frozen=True)
class LLMUsage:
    calls: int
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    source: str


class LLMClient(Protocol):
    def complete(self, *, prompt: str, output_name: str) -> str:
        """Return raw model text for a named structured output contract."""


def parse_structured_output(raw_output: str, output_model: type[OutputT]) -> OutputT:
    try:
        return output_model.model_validate_json(raw_output)
    except ValidationError as exc:
        errors = [
            {
                "location": ".".join(str(part) for part in error["loc"]),
                "type": error["type"],
                "message": error.get("msg", ""),
            }
            for error in exc.errors()
        ]
        raise SchemaValidationError(
            f"{output_model.__name__} output failed schema validation",
            details={"output_name": output_model.__name__, "errors": errors},
        ) from exc


class FakeLLM:
    """Deterministic LLM double keyed by structured output name."""

    def __init__(self, responses: Mapping[str, str]) -> None:
        self._responses = dict(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, prompt: str, output_name: str) -> str:
        self.calls.append((prompt, output_name))
        if output_name not in self._responses:
            raise ToolExecutionError(
                "fake LLM has no response for output contract",
                details={"output_name": output_name},
            )
        return self._responses[output_name]

    def usage(self) -> LLMUsage:
        return LLMUsage(
            calls=len(self.calls),
            input_tokens=None,
            output_tokens=None,
            estimated_cost_usd=None,
            source="fake",
        )


class OpenAICompatibleLLMClient:
    """Minimal OpenAI-compatible Chat Completions adapter.

    It intentionally exposes only structured raw text and usage accounting.
    Provider-specific tools, streaming, and hidden system behavior are not used.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not base_url or not api_key or not model:
            raise ValueError("base_url, api_key, and model are required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._calls = 0
        self._input_tokens: int | None = None
        self._output_tokens: int | None = None

    def complete(self, *, prompt: str, output_name: str) -> str:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(
                {
                    "model": self.model,
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Return only valid JSON for the requested output "
                                "contract. Do not include markdown fences."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"{prompt}\nOutput contract: {output_name}",
                        },
                    ],
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ExternalServiceUnavailableError(
                "LLM API request failed",
                details={
                    "provider": "openai-compatible",
                    "reason": type(exc).__name__,
                    "http_status": exc.code,
                },
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ExternalServiceUnavailableError(
                "LLM API request failed",
                details={"provider": "openai-compatible", "reason": type(exc).__name__},
            ) from exc

        self._calls += 1
        usage = payload.get("usage") or {}
        if isinstance(usage.get("prompt_tokens"), int):
            self._input_tokens = (self._input_tokens or 0) + usage["prompt_tokens"]
        if isinstance(usage.get("completion_tokens"), int):
            self._output_tokens = (self._output_tokens or 0) + usage["completion_tokens"]

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExternalServiceUnavailableError(
                "LLM API response did not contain message content",
                details={"provider": "openai-compatible"},
            ) from exc
        if not isinstance(content, str):
            raise ExternalServiceUnavailableError(
                "LLM API content was not text",
                details={"provider": "openai-compatible"},
            )
        return content

    def usage(self) -> LLMUsage:
        return LLMUsage(
            calls=self._calls,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            estimated_cost_usd=None,
            source="actual",
        )


def build_llm_client(config: object) -> LLMClient | None:
    """Build a real client only when explicitly configured and supported."""

    llm_config = getattr(config, "llm", None)
    if llm_config is None or not llm_config.enabled:
        return None
    provider = (llm_config.provider or "").lower()
    if provider not in {"openai", "openai-compatible"}:
        raise ExternalServiceUnavailableError(
            "configured LLM provider is not supported by the current adapter",
            details={"provider": provider or "unknown"},
        )
    if not llm_config.base_url or not llm_config.api_key or not llm_config.model:
        raise ExternalServiceUnavailableError(
            "enabled LLM provider is missing base_url, api_key, or model",
            details={"provider": provider},
        )
    return OpenAICompatibleLLMClient(
        base_url=llm_config.base_url,
        api_key=llm_config.api_key.get_secret_value(),
        model=llm_config.model,
    )
