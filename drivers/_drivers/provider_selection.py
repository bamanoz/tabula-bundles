#!/usr/bin/env python3
"""Shared provider selection for Tabula gateways and bootstrap."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from skills._pylib.paths import skills_dir
from skills._pylib.config import SkillConfigError, load_global_config, load_skill_config


PROVIDER_ALIASES = {
    "anthropic": "anthropic",
    "claude": "anthropic",
    "openai": "openai",
    "gpt": "openai",
    "openclaw": "openai",
    "mock": "mock",
}


class ProviderSelectionError(RuntimeError):
    pass


def _tabula_home(tabula_home: str | Path | None = None) -> Path:
    if tabula_home is not None:
        return Path(tabula_home)
    return Path(os.environ.get("TABULA_HOME", os.path.expanduser("~/.tabula")))


def configured_provider(*, tabula_home: str | Path | None = None) -> str | None:
    env_provider = os.environ.get("TABULA_PROVIDER", "").strip()
    if env_provider:
        return env_provider
    global_cfg = load_global_config(tabula_home_override=_tabula_home(tabula_home))
    provider = str(global_cfg.get("provider", "")).strip()
    return provider or None


def normalize_provider(requested: str | None, *, default_provider: str | None = None) -> str:
    raw = (requested or default_provider or "").strip().lower()
    if not raw:
        raise ProviderSelectionError("no provider configured; set TABULA_PROVIDER or pass --provider")
    provider = PROVIDER_ALIASES.get(raw)
    if not provider:
        supported = ", ".join(sorted(PROVIDER_ALIASES.keys()))
        raise ProviderSelectionError(f"unknown provider {raw!r}; supported values: {supported}")
    return provider


def provider_skill_dir(provider: str, *, tabula_home: str | Path | None = None) -> Path:
    if tabula_home is not None:
        home = _tabula_home(tabula_home)
        return home / "skills" / "driver"
    return skills_dir() / "driver"


def unified_driver_script_path(*, tabula_home: str | Path | None = None) -> Path:
    if tabula_home is not None:
        home = _tabula_home(tabula_home)
        return home / "skills" / "driver" / "run.py"
    return skills_dir() / "driver" / "run.py"


def provider_script_path(provider: str, *, tabula_home: str | Path | None = None) -> Path:
    return unified_driver_script_path(tabula_home=tabula_home)


def ensure_provider_installed(provider: str, *, tabula_home: str | Path | None = None) -> Path:
    normalize_provider(provider)
    script = unified_driver_script_path(tabula_home=tabula_home)
    if not script.is_file():
        raise ProviderSelectionError(f"unified driver is not installed; driver script not found: {script}")
    return script


def ensure_provider_ready(provider: str, *, tabula_home: str | Path | None = None) -> dict:
    provider = normalize_provider(provider)
    skill_dir = provider_skill_dir(provider, tabula_home=tabula_home)
    ensure_provider_installed(provider, tabula_home=tabula_home)
    try:
        settings = load_skill_config(skill_dir, tabula_home_override=_tabula_home(tabula_home))
    except SkillConfigError as exc:
        raise ProviderSelectionError(f"provider {provider!r} is not configured: {exc}") from exc
    prefix = provider.replace("-", "_")
    required_key = f"{prefix}_api_key"
    if not settings.get(required_key):
        raise ProviderSelectionError(f"provider {provider!r} is not configured: missing {required_key}")
    return settings


def resolve_provider(
    requested: str | None = None,
    *,
    tabula_home: str | Path | None = None,
    require_ready: bool = True,
    default_provider: str | None = None,
) -> str:
    if default_provider is None:
        default_provider = configured_provider(tabula_home=tabula_home)
    provider = normalize_provider(requested, default_provider=default_provider)
    ensure_provider_installed(provider, tabula_home=tabula_home)
    if require_ready:
        ensure_provider_ready(provider, tabula_home=tabula_home)
    return provider


def build_driver_command(
    provider: str,
    *,
    tabula_home: str | Path | None = None,
    python_executable: str | None = None,
) -> str:
    ensure_provider_ready(provider, tabula_home=tabula_home)
    script = unified_driver_script_path(tabula_home=tabula_home)
    if not script.is_file():
        raise ProviderSelectionError(f"unified driver is not installed; driver script not found: {script}")
    python_executable = python_executable or sys.executable
    return shlex.join([python_executable, str(script), "--provider", provider])


def resolve_driver_command(
    requested: str | None = None,
    *,
    tabula_home: str | Path | None = None,
    python_executable: str | None = None,
    default_provider: str | None = None,
) -> tuple[str, str]:
    provider = resolve_provider(
        requested,
        tabula_home=tabula_home,
        require_ready=True,
        default_provider=default_provider,
    )
    return provider, build_driver_command(provider, tabula_home=tabula_home, python_executable=python_executable)
