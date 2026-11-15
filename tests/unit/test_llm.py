import io
import json
from unittest.mock import patch

import pytest

from repopilot.core.config import load_config
from repopilot.core.errors import ExternalServiceUnavailableError
from repopilot.llm import (
    FakeLLM,
    OpenAICompatibleLLMClient,
    build_llm_client,
)


class _Response:
    def __init__(self, payload: dict) -> None:
        self._bytes = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._bytes


def test_fake_llm_reports_fake_usage_without_api_key() -> None:
    llm = FakeLLM({"TaskPlan": '{"ok":true}'})
    assert llm.complete(prompt="prompt", output_name="TaskPlan") == '{"ok":true}'
    usage = llm.usage()

    assert usage.calls == 1
    assert usage.source == "fake"
    assert usage.input_tokens is None


def test_real_llm_client_is_disabled_without_configuration() -> None:
    assert build_llm_client(load_config(env={})) is None


def test_enabled_real_llm_requires_complete_configuration() -> None:
    config = load_config(
        env={
            "LLM_ENABLED": "true",
            "LLM_PROVIDER": "openai-compatible",
            "LLM_MODEL": "model",
        }
    )

    with pytest.raises(ExternalServiceUnavailableError):
        build_llm_client(config)


def test_openai_compatible_adapter_parses_json_and_usage() -> None:
    payload = {
        "choices": [{"message": {"content": '{"ok":true}'}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }
    client = OpenAICompatibleLLMClient(
        base_url="https://example.invalid/v1",
        api_key="sk-test-key",
        model="test-model",
    )

    with patch(
        "urllib.request.urlopen",
        return_value=_Response(payload),
    ) as mocked:
        content = client.complete(prompt="return a contract", output_name="TaskPlan")

    assert content == '{"ok":true}'
    usage = client.usage()
    assert usage.calls == 1
    assert usage.input_tokens == 7
    assert usage.output_tokens == 3
    assert usage.source == "actual"
    request = mocked.call_args.args[0]
    assert request.full_url.endswith("/chat/completions")
    assert request.get_header("Authorization") == "Bearer sk-test-key"
