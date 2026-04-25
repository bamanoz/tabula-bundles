#!/usr/bin/env python3
"""Unified Tabula LLM subagent runner."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = os.environ.get("TABULA_HOME", os.path.expanduser("~/.tabula"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from skills._pylib import SkillConfigError
from skills._pylib.paths import ensure_parent, skill_logs_dir
from skills._drivers.provider_factory import create_provider_session, load_provider_settings
from skills._drivers.provider_selection import configured_provider, normalize_provider
from skills._drivers.subagent_runtime import SubagentConfig, SubagentRuntime


TABULA_URL = os.environ.get("TABULA_URL", "ws://localhost:8089/ws")
TABULA_SPAWN_TOKEN = os.environ.get("TABULA_SPAWN_TOKEN", "")
DEFAULT_IDLE_TIMEOUT = 0
VERBOSE = os.environ.get("TABULA_VERBOSE", "") == "1"


def make_logger(provider: str):
    log_file = str(skill_logs_dir("subagent") / f"{provider}.log")

    def log(msg: str):
        if VERBOSE:
            sys.stderr.write(f"[subagent:{provider}] {msg}\n")
            sys.stderr.flush()
            try:
                with open(ensure_parent(Path(log_file)), "a") as handle:
                    handle.write(f"[{time.time():.1f}] {msg}\n")
            except Exception:
                pass

    return log


def main():
    parser = argparse.ArgumentParser(description="Tabula unified LLM subagent")
    parser.add_argument("--provider", default=None, help="Provider: openai or anthropic")
    parser.add_argument("--id", required=True)
    parser.add_argument("--parent-session", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=int, default=DEFAULT_IDLE_TIMEOUT)
    parser.add_argument("--max-turns", type=int, default=20)
    args = parser.parse_args()

    try:
        provider = normalize_provider(args.provider, default_provider=configured_provider())
        settings = load_provider_settings(provider, model_override=args.model)
    except (SkillConfigError, RuntimeError) as exc:
        sys.stderr.write(f"[subagent] ERROR: {exc}\n")
        sys.stderr.flush()
        sys.exit(1)

    max_turns = min(args.max_turns, 50)
    session_name = f"subagent-{args.id}"
    log = make_logger(provider)

    runtime = SubagentRuntime(
        SubagentConfig(
            name=session_name,
            provider=provider,
            url=TABULA_URL,
            session_name=session_name,
            parent_session=args.parent_session,
            agent_id=args.id,
            initial_task=args.task,
            idle_timeout=args.timeout,
            max_turns=max_turns,
            spawn_token=TABULA_SPAWN_TOKEN,
        ),
        provider_factory=lambda prompt, tools: create_provider_session(
            settings,
            system_prompt=prompt + f"\n\nYou have a budget of {max_turns} llm turns. Plan your work to finish within this limit.",
            tools=tools,
        ),
        logger=log,
    )

    runtime.connect()
    runtime.run()


if __name__ == "__main__":
    main()
