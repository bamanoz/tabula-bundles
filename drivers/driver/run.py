#!/usr/bin/env python3
"""Unified Tabula main LLM driver."""

from __future__ import annotations

import argparse
import os
import signal
import sys

ROOT = os.environ.get("TABULA_HOME", os.path.expanduser("~/.tabula"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from skills._pylib import SkillConfigError
from skills._drivers.driver_runtime import DriverConfig, DriverRuntime
from skills._drivers.provider_factory import create_provider_session, load_provider_settings
from skills._drivers.provider_selection import configured_provider, normalize_provider


TABULA_URL = os.environ.get("TABULA_URL", "ws://localhost:8089/ws")
VERBOSE = os.environ.get("TABULA_VERBOSE", "") == "1"


def make_logger(provider: str):
    def log(msg: str):
        if VERBOSE:
            sys.stderr.write(f"[driver:{provider}] {msg}\n")
            sys.stderr.flush()

    return log


def main():
    parser = argparse.ArgumentParser(description="Tabula unified LLM driver")
    parser.add_argument("--session", default="main", help="Session to join")
    parser.add_argument("--provider", default=None, help="Provider: openai or anthropic")
    parser.add_argument("--model", default=None, help="Provider model override for this driver process")
    args = parser.parse_args()

    try:
        provider = normalize_provider(args.provider, default_provider=configured_provider())
        settings = load_provider_settings(provider, model_override=args.model)
    except (SkillConfigError, RuntimeError) as exc:
        sys.stderr.write(f"[driver] ERROR: {exc}\n")
        sys.stderr.flush()
        sys.exit(1)

    log = make_logger(provider)
    runtime = DriverRuntime(
        DriverConfig(name=provider, url=TABULA_URL, session=args.session),
        provider_factory=lambda prompt, tools, turn_provider=None, turn_model=None: create_provider_session(
            load_provider_settings(turn_provider or settings.provider, model_override=turn_model or args.model),
            system_prompt=prompt,
            tools=tools,
        ),
        logger=log,
    )

    def handle_sigint(sig, frame):
        log("SIGINT received, shutting down")
        runtime.abort()
        runtime.conn.close()

    signal.signal(signal.SIGINT, handle_sigint)

    log(f"connecting to {TABULA_URL}")
    try:
        runtime.connect()
        runtime.run()
    finally:
        runtime.close()
        runtime.conn.close()


if __name__ == "__main__":
    main()
