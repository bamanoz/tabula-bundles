#!/usr/bin/env python3
"""Agent catalog loading and per-turn model/provider resolution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore


@dataclass(frozen=True)
class AgentConfig:
    name: str
    description: str = ""
    mode: str = "primary"
    provider: str | None = None
    model: str | None = None
    prompt: str = ""


@dataclass(frozen=True)
class TurnConfig:
    agent: AgentConfig
    provider: str
    model: str | None


def tabula_home() -> Path:
    return Path(os.environ.get("TABULA_HOME", os.path.expanduser("~/.tabula")))


def _parse_scalar(raw: str):
    value = raw.strip().strip('"').strip("'")
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text.strip()
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text.strip()
    raw = text[3:end].strip()
    body = text[end + 4 :].strip()
    meta: dict = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        meta[key.strip()] = _parse_scalar(value)
    return meta, body


def _load_markdown_agent(path: Path) -> AgentConfig | None:
    try:
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    name = str(meta.get("name") or path.stem).strip()
    if not name:
        return None
    return AgentConfig(
        name=name,
        description=str(meta.get("description") or ""),
        mode=str(meta.get("mode") or "primary"),
        provider=str(meta["provider"]) if meta.get("provider") else None,
        model=str(meta["model"]) if meta.get("model") else None,
        prompt=body,
    )


def _agent_dirs(home: Path) -> list[Path]:
    return [
        home / "distrib" / "active" / "current" / "agents",
        home / "agents",
    ]


def load_agents(home: Path | None = None) -> dict[str, AgentConfig]:
    home = home or tabula_home()
    agents: dict[str, AgentConfig] = {}
    for directory in _agent_dirs(home):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            agent = _load_markdown_agent(path)
            if agent:
                agents[agent.name] = agent
    if "build" not in agents:
        agents["build"] = AgentConfig(name="build", description="Default coding agent")
    return agents


def serialize_agents(agents: dict[str, AgentConfig]) -> list[dict]:
    return [
        {
            "name": agent.name,
            "description": agent.description,
            "mode": agent.mode,
            "provider": agent.provider,
            "model": agent.model,
        }
        for agent in sorted(agents.values(), key=lambda a: a.name)
    ]


def split_model(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    value = value.strip()
    if "/" in value:
        provider, model = value.split("/", 1)
        return provider or None, model or None
    return None, value or None


def resolve_turn(
    agents: dict[str, AgentConfig],
    *,
    agent_name: str | None,
    model_meta,
    default_provider: str,
    default_model: str | None,
) -> TurnConfig:
    agent = agents.get(agent_name or "") or agents.get("build") or next(iter(agents.values()))
    provider = agent.provider or default_provider
    model = agent.model or default_model

    if isinstance(model_meta, str):
        p, m = split_model(model_meta)
        provider = p or provider
        model = m or model
    elif isinstance(model_meta, dict):
        raw_provider = model_meta.get("provider") or model_meta.get("providerID")
        raw_model = model_meta.get("model") or model_meta.get("id") or model_meta.get("modelID")
        if isinstance(raw_provider, str) and raw_provider.strip():
            provider = raw_provider.strip()
        if isinstance(raw_model, str) and raw_model.strip():
            p, m = split_model(raw_model)
            provider = p or provider
            model = m or model

    return TurnConfig(agent=agent, provider=provider, model=model)
