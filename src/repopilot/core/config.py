"""Unified configuration loading for YAML files and environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

from repopilot.core.errors import ConfigurationError


class ServiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    enabled: bool = False
    provider: str | None = None
    model: str | None = None
    api_key: SecretStr | None = None
    base_url: str | None = None

    @model_validator(mode="after")
    def validate_enabled_service(self) -> "ServiceConfig":
        if self.enabled and (not self.provider or not self.model):
            raise ValueError("enabled services require provider and model")
        return self


class LLMConfig(ServiceConfig):
    pass


class EmbeddingConfig(ServiceConfig):
    pass


class RerankerConfig(ServiceConfig):
    pass


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    backend: str = Field(default="sqlite", pattern="^(sqlite|postgresql)$")
    url: SecretStr = SecretStr("sqlite:///./repopilot.db")

    @model_validator(mode="after")
    def validate_backend_url(self) -> "DatabaseConfig":
        url = self.url.get_secret_value()
        if self.backend == "sqlite" and not url.startswith("sqlite:"):
            raise ValueError("sqlite backend requires a sqlite: URL")
        if self.backend == "postgresql" and not url.startswith(("postgresql:", "postgres:")):
            raise ValueError("postgresql backend requires a postgresql: URL")
        return self


class CheckpointerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    backend: str = Field(default="sqlite", pattern="^(memory|sqlite|postgresql)$")


class SandboxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    backend: str = Field(default="local_worktree", pattern="^(local_worktree|docker)$")
    network_disabled: bool = True
    timeout_seconds: int = Field(default=300, ge=1, le=3_600)


class BudgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    max_llm_calls: int = Field(default=30, ge=1, le=1_000)
    max_total_tokens: int = Field(default=100_000, ge=1)
    max_runtime_seconds: int = Field(default=900, ge=1, le=86_400)
    max_patch_retries: int = Field(default=3, ge=0, le=10)
    max_replans: int = Field(default=2, ge=0, le=10)
    max_tool_retries: int = Field(default=2, ge=0, le=10)
    max_tool_calls: int = Field(default=100, ge=1, le=10_000)


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    format: str = Field(default="json", pattern="^(json|text)$")


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    environment: str = Field(default="development", pattern="^(development|test|production)$")
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    checkpointer: CheckpointerConfig = Field(default_factory=CheckpointerConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @model_validator(mode="after")
    def validate_backend_compatibility(self) -> "AppConfig":
        if self.checkpointer.backend == "postgresql" and self.database.backend != "postgresql":
            raise ValueError("postgresql checkpointer requires a postgresql database")
        return self


_ENV_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "REPOPILOT_ENV": ("environment",),
    "LLM_ENABLED": ("llm", "enabled"),
    "LLM_PROVIDER": ("llm", "provider"),
    "LLM_MODEL": ("llm", "model"),
    "LLM_API_KEY": ("llm", "api_key"),
    "LLM_BASE_URL": ("llm", "base_url"),
    "EMBEDDING_ENABLED": ("embedding", "enabled"),
    "EMBEDDING_PROVIDER": ("embedding", "provider"),
    "EMBEDDING_MODEL": ("embedding", "model"),
    "EMBEDDING_API_KEY": ("embedding", "api_key"),
    "EMBEDDING_BASE_URL": ("embedding", "base_url"),
    "RERANKER_ENABLED": ("reranker", "enabled"),
    "RERANKER_PROVIDER": ("reranker", "provider"),
    "RERANKER_MODEL": ("reranker", "model"),
    "RERANKER_API_KEY": ("reranker", "api_key"),
    "RERANKER_BASE_URL": ("reranker", "base_url"),
    "DATABASE_BACKEND": ("database", "backend"),
    "DATABASE_URL": ("database", "url"),
    "CHECKPOINTER_BACKEND": ("checkpointer", "backend"),
    "SANDBOX_BACKEND": ("sandbox", "backend"),
    "SANDBOX_NETWORK_DISABLED": ("sandbox", "network_disabled"),
    "SANDBOX_TIMEOUT_SECONDS": ("sandbox", "timeout_seconds"),
    "MAX_LLM_CALLS": ("budget", "max_llm_calls"),
    "MAX_TOTAL_TOKENS": ("budget", "max_total_tokens"),
    "MAX_RUNTIME_SECONDS": ("budget", "max_runtime_seconds"),
    "MAX_PATCH_RETRIES": ("budget", "max_patch_retries"),
    "MAX_REPLANS": ("budget", "max_replans"),
    "MAX_TOOL_RETRIES": ("budget", "max_tool_retries"),
    "LOG_LEVEL": ("logging", "level"),
    "LOG_FORMAT": ("logging", "format"),
}


def _set_nested(values: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    target = values
    for key in path[:-1]:
        target = target.setdefault(key, {})
    target[path[-1]] = value


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except OSError as exc:
        raise ConfigurationError(
            "unable to read configuration file",
            details={"config_path": str(path), "reason": type(exc).__name__},
        ) from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(
            "configuration file is not valid YAML",
            details={"config_path": str(path), "reason": type(exc).__name__},
        ) from exc

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigurationError(
            "configuration file must contain a YAML mapping",
            details={"config_path": str(path)},
        )
    return loaded


def load_config(
    config_path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> AppConfig:
    """Load defaults, optional YAML config, then environment overrides."""

    environment = dict(os.environ if env is None else env)
    selected_path = config_path or environment.get("REPOPILOT_CONFIG") or None
    values: dict[str, Any] = _load_yaml(Path(selected_path)) if selected_path else {}

    for env_name, field_path in _ENV_FIELD_MAP.items():
        if env_name not in environment:
            continue
        raw_value = environment[env_name]
        if raw_value == "":
            continue
        _set_nested(values, field_path, raw_value)

    try:
        return AppConfig.model_validate(values)
    except ValidationError as exc:
        errors = [
            {
                "location": ".".join(str(part) for part in error["loc"]),
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        raise ConfigurationError(
            "configuration validation failed",
            details={"error_count": len(errors), "errors": errors},
        ) from exc
