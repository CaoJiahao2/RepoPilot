from pathlib import Path

import pytest

from repopilot.core.config import load_config
from repopilot.core.errors import ConfigurationError


def test_defaults_disable_optional_external_services() -> None:
    config = load_config(env={})

    assert config.environment == "development"
    assert config.llm.enabled is False
    assert config.embedding.enabled is False
    assert config.reranker.enabled is False
    assert config.database.backend == "sqlite"
    assert config.sandbox.backend == "local_worktree"
    assert config.budget.max_llm_calls == 30


def test_yaml_values_are_loaded_and_environment_overrides(tmp_path: Path) -> None:
    config_file = tmp_path / "app.yaml"
    config_file.write_text(
        """
environment: test
llm:
  enabled: true
  provider: yaml-provider
  model: yaml-model
budget:
  max_llm_calls: 5
logging:
  level: WARNING
  format: text
""",
        encoding="utf-8",
    )

    config = load_config(
        config_file,
        env={
            "LLM_PROVIDER": "env-provider",
            "MAX_LLM_CALLS": "9",
            "LOG_LEVEL": "ERROR",
        },
    )

    assert config.environment == "test"
    assert config.llm.provider == "env-provider"
    assert config.llm.model == "yaml-model"
    assert config.budget.max_llm_calls == 9
    assert config.logging.level == "ERROR"
    assert config.logging.format == "text"


def test_config_path_can_be_selected_by_environment(tmp_path: Path) -> None:
    config_file = tmp_path / "selected.yaml"
    config_file.write_text("environment: production\n", encoding="utf-8")

    config = load_config(env={"REPOPILOT_CONFIG": str(config_file)})

    assert config.environment == "production"


def test_empty_environment_values_do_not_erase_file_values(tmp_path: Path) -> None:
    config_file = tmp_path / "app.yaml"
    config_file.write_text("environment: test\n", encoding="utf-8")

    config = load_config(config_file, env={"REPOPILOT_ENV": ""})

    assert config.environment == "test"


def test_enabled_optional_service_requires_provider_and_model() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        load_config(env={"EMBEDDING_ENABLED": "true", "EMBEDDING_PROVIDER": "provider"})

    assert exc_info.value.code.value == "configuration_error"
    assert "configuration validation failed" in exc_info.value.message


def test_invalid_config_file_type_is_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "bad.yaml"
    config_file.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="must contain a YAML mapping"):
        load_config(config_file, env={})


def test_missing_config_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="unable to read configuration file"):
        load_config(tmp_path / "missing.yaml", env={})


def test_secret_values_are_masked_in_model_repr() -> None:
    secret = "sk-super-secret-value"

    config = load_config(
        env={
            "LLM_ENABLED": "true",
            "LLM_PROVIDER": "test-provider",
            "LLM_MODEL": "test-model",
            "LLM_API_KEY": secret,
        }
    )

    assert config.llm.api_key is not None
    assert config.llm.api_key.get_secret_value() == secret
    assert secret not in repr(config)
