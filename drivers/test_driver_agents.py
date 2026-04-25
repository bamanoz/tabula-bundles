#!/usr/bin/env python3
"""Tests for unified driver agent/model turn selection."""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT.parent / "tabula"
sys.path.insert(0, str(ROOT / "drivers"))
if CORE.is_dir():
    sys.path.insert(0, str(CORE))

try:
    import websocket  # noqa: F401
except ModuleNotFoundError:
    websocket_stub = types.ModuleType("websocket")
    websocket_stub.WebSocketTimeoutException = TimeoutError
    websocket_stub.WebSocketConnectionClosedException = ConnectionError
    websocket_stub.create_connection = lambda _url: None
    sys.modules["websocket"] = websocket_stub

from _drivers.agents import load_agents, resolve_turn, serialize_agents  # noqa: E402
from _drivers import driver_runtime  # noqa: E402


def write_agent(path: Path, name: str, description: str, body: str, *, provider: str = "", model: str = ""):
    provider_line = f"provider: {provider}\n" if provider else ""
    model_line = f"model: {model}\n" if model else ""
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\nmode: primary\n{provider_line}{model_line}---\n{body}\n",
        encoding="utf-8",
    )


class FakeConnection:
    def __init__(self, url: str):
        self.url = url
        self.sent: list[dict] = []

    def send(self, msg: dict):
        self.sent.append(msg)


class FakeProvider:
    def __init__(self, *, prompt: str, provider: str, model: str | None):
        self.system_prompt = prompt
        self.provider = provider
        self.model = model or ""
        self.messages: list[dict] = []
        self.restored: list[dict] = []

    def add_user_text(self, text: str):
        self.messages.append({"role": "user", "text": text})

    def add_tool_results(self, results):
        self.messages.append({"role": "tool", "results": results})

    def generate(self, on_text_delta):
        raise AssertionError("process_turn should be stubbed in these tests")

    def abort(self):
        pass

    def record_aborted_turn(self):
        pass

    def restore_history(self, entries: list[dict]):
        self.restored.extend(entries)

    def needs_compact(self) -> bool:
        return False

    def compact(self, logger=None) -> str:
        return ""


class AgentCatalogTests(unittest.TestCase):
    def test_loads_distro_agents_and_user_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            distro_agents = home / "distrib" / "active" / "current" / "agents"
            user_agents = home / "agents"
            distro_agents.mkdir(parents=True)
            user_agents.mkdir(parents=True)
            write_agent(distro_agents / "build.md", "build", "Build", "build prompt")
            write_agent(distro_agents / "plan.md", "plan", "Plan", "distro plan")
            write_agent(user_agents / "plan.md", "plan", "User plan", "user plan", provider="anthropic", model="claude-4")

            agents = load_agents(home)
            self.assertEqual(sorted(agents), ["build", "plan"])
            self.assertEqual(agents["plan"].description, "User plan")
            self.assertEqual(agents["plan"].provider, "anthropic")
            self.assertEqual(agents["plan"].model, "claude-4")
            self.assertEqual([item["name"] for item in serialize_agents(agents)], ["build", "plan"])

    def test_resolve_turn_uses_message_model_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            agent_dir = home / "distrib" / "active" / "current" / "agents"
            agent_dir.mkdir(parents=True)
            write_agent(agent_dir / "build.md", "build", "Build", "build prompt")
            write_agent(agent_dir / "plan.md", "plan", "Plan", "plan prompt", provider="anthropic", model="claude-default")

            turn = resolve_turn(
                load_agents(home),
                agent_name="plan",
                model_meta="openai/gpt-5.5",
                default_provider="openai",
                default_model=None,
            )

            self.assertEqual(turn.agent.name, "plan")
            self.assertEqual(turn.provider, "openai")
            self.assertEqual(turn.model, "gpt-5.5")


class DriverRuntimeTurnTests(unittest.TestCase):
    def setUp(self):
        if not CORE.is_dir():
            self.skipTest("tabula core checkout not found next to tabula-bundles")
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.old_home = os.environ.get("TABULA_HOME")
        os.environ["TABULA_HOME"] = str(self.home)
        agent_dir = self.home / "distrib" / "active" / "current" / "agents"
        agent_dir.mkdir(parents=True)
        write_agent(agent_dir / "build.md", "build", "Build", "build prompt")
        write_agent(agent_dir / "plan.md", "plan", "Plan", "plan prompt")

        self.old_connection = driver_runtime.KernelConnection
        self.old_prompt_builder = driver_runtime.build_main_system_prompt
        driver_runtime.KernelConnection = FakeConnection
        self.prompt_calls: list[dict] = []

        def fake_prompt(*, provider: str, agent_name: str, agent_prompt: str, visible_tools: list[dict]):
            self.prompt_calls.append(
                {
                    "provider": provider,
                    "agent_name": agent_name,
                    "agent_prompt": agent_prompt,
                    "visible_tools": visible_tools,
                }
            )
            return f"prompt provider={provider} agent={agent_name}\n{agent_prompt}"

        driver_runtime.build_main_system_prompt = fake_prompt

    def tearDown(self):
        driver_runtime.KernelConnection = self.old_connection
        driver_runtime.build_main_system_prompt = self.old_prompt_builder
        if self.old_home is None:
            os.environ.pop("TABULA_HOME", None)
        else:
            os.environ["TABULA_HOME"] = self.old_home
        self.tmp.cleanup()

    def test_message_meta_selects_agent_provider_and_model_per_turn(self):
        provider_calls: list[dict] = []

        def provider_factory(prompt: str, tools: list[dict], turn_provider: str | None = None, turn_model: str | None = None):
            provider_calls.append(
                {
                    "prompt": prompt,
                    "tools": tools,
                    "provider": turn_provider,
                    "model": turn_model,
                }
            )
            return FakeProvider(prompt=prompt, provider=turn_provider or "", model=turn_model)

        runtime = driver_runtime.DriverRuntime(
            driver_runtime.DriverConfig(name="openai", url="ws://127.0.0.1:1/ws", session="main"),
            provider_factory=provider_factory,
            logger=lambda _msg: None,
        )
        runtime.process_turn = lambda suppress_stream=False: None
        runtime.handle_init({"tools": [{"name": "shell_exec"}], "context": "workspace context"})

        runtime.handle_message(
            {
                "type": "message",
                "text": "plan this",
                "meta": {"agent": "plan", "model": "anthropic/claude-4"},
            }
        )

        self.assertGreaterEqual(len(provider_calls), 2)
        selected = provider_calls[-1]
        self.assertEqual(selected["provider"], "anthropic")
        self.assertEqual(selected["model"], "claude-4")
        self.assertIn("agent=plan", selected["prompt"])
        self.assertIn("plan prompt", selected["prompt"])
        self.assertIn("workspace context", selected["prompt"])
        self.assertEqual(runtime.provider.messages[-1], {"role": "user", "text": "plan this"})
        runtime.close()

    def test_provider_only_model_meta_defers_to_provider_default_model(self):
        provider_calls: list[dict] = []

        def provider_factory(prompt: str, tools: list[dict], turn_provider: str | None = None, turn_model: str | None = None):
            provider_calls.append({"provider": turn_provider, "model": turn_model})
            return FakeProvider(prompt=prompt, provider=turn_provider or "", model=turn_model)

        runtime = driver_runtime.DriverRuntime(
            driver_runtime.DriverConfig(name="openai", url="ws://127.0.0.1:1/ws", session="main"),
            provider_factory=provider_factory,
            logger=lambda _msg: None,
        )
        runtime.process_turn = lambda suppress_stream=False: None
        runtime.handle_init({"tools": []})

        runtime.handle_message({"type": "message", "text": "switch provider", "meta": {"model": "anthropic/"}})

        selected = provider_calls[-1]
        self.assertEqual(selected["provider"], "anthropic")
        self.assertIsNone(selected["model"])
        runtime.close()


if __name__ == "__main__":
    unittest.main()
