#!/usr/bin/env python3
"""Provider adapter factory for unified Tabula drivers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skills._pylib import SkillConfigError, load_skill_config

from .providers import AnthropicSession, OpenAIChatCompletionsSession, ProviderSession


SUPPORTED_PROVIDERS = {"anthropic", "openai"}


@dataclass(frozen=True)
class ProviderSettings:
    provider: str
    api_key: str
    base_url: str
    model: str


def provider_skill_dir(provider: str) -> Path:
    return Path(__file__).resolve().parent.parent / "driver"


def load_provider_settings(provider: str, *, model_override: str | None = None) -> ProviderSettings:
    if provider not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise SkillConfigError(f"unsupported provider {provider!r}; supported values: {supported}")
    settings = load_skill_config(provider_skill_dir(provider))
    prefix = provider.replace("-", "_")
    model = model_override or str(settings[f"{prefix}_model"])
    return ProviderSettings(
        provider=provider,
        api_key=str(settings[f"{prefix}_api_key"]),
        base_url=str(settings[f"{prefix}_base_url"]),
        model=model,
    )


def create_provider_session(settings: ProviderSettings, *, system_prompt: str, tools: list[dict]) -> ProviderSession:
    if settings.provider == "anthropic":
        return AnthropicSession(
            system_prompt=system_prompt,
            model=settings.model,
            api_key=settings.api_key,
            base_url=settings.base_url,
            tools=tools,
        )
    if settings.provider == "openai":
        return OpenAIChatCompletionsSession(
            system_prompt=system_prompt,
            model=settings.model,
            api_key=settings.api_key,
            base_url=settings.base_url,
            tools=tools,
        )
    raise AssertionError(f"unhandled provider: {settings.provider}")
