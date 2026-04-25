#!/usr/bin/env python3
"""hook-workspace-boundary — block file-tool calls outside project_root."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = os.environ.get("TABULA_HOME", os.path.expanduser("~/.tabula"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from skills._pylib.paths import skill_config_dir
from skills._pylib.kernel_client import KernelConnection
from skills._pylib.protocol import (
    MSG_CONNECT, MSG_HOOK, MSG_HOOK_RESULT, HOOK_PASS, HOOK_BLOCK,
    HOOK_BEFORE_TOOL_CALL,
)

TABULA_URL = os.environ.get("TABULA_URL", "ws://localhost:8089/ws")
CONFIG_FILE = skill_config_dir("hook-workspace-boundary") / "config.json"

# Tools whose `path` param refers to a filesystem location.
PATH_TOOLS = {"read", "write", "edit", "multiedit", "list_dir", "glob", "grep"}

# Regex to find file paths inside apply_patch patch_text.
_PATCH_PATH_RE = re.compile(
    r"^\*\*\*\s+(?:Add|Update|Delete)\s+File:\s*(.+?)\s*$",
    re.MULTILINE,
)
_PATCH_MOVE_RE = re.compile(r"^\*\*\*\s+Move\s+to:\s*(.+?)\s*$", re.MULTILINE)


def load_config() -> dict:
    if not CONFIG_FILE.is_file():
        return {"enabled": True, "allow_outside": []}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"hook-workspace-boundary: invalid config: {exc}", file=sys.stderr)
        return {"enabled": True, "allow_outside": []}
    if not isinstance(data, dict):
        return {"enabled": True, "allow_outside": []}
    enabled = data.get("enabled", True)
    allow = data.get("allow_outside", [])
    if not isinstance(allow, list):
        allow = []
    allow = [str(p) for p in allow if isinstance(p, str) and p.strip()]
    return {"enabled": bool(enabled), "allow_outside": allow}


def project_root() -> str | None:
    value = os.environ.get("TABULA_PROJECT_ROOT", "").strip()
    return value or None


def _resolve(path: str, base: str) -> Path:
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        p = Path(base) / p
    try:
        return p.resolve()
    except OSError:
        return p


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _allowed(path: Path, root: Path, allow_outside: list[str]) -> bool:
    if _is_under(path, root):
        return True
    for prefix in allow_outside:
        try:
            prefix_p = Path(os.path.expanduser(prefix)).resolve()
        except OSError:
            continue
        if _is_under(path, prefix_p):
            return True
    return False


def extract_paths(tool_name: str, raw_input) -> list[str]:
    """Return all filesystem paths implied by the tool call."""
    if raw_input is None:
        return []
    try:
        inp = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(inp, dict):
        return []

    if tool_name in PATH_TOOLS:
        path = inp.get("path")
        if isinstance(path, str) and path.strip():
            return [path]
        return []

    if tool_name == "apply_patch":
        text = inp.get("patch_text")
        if not isinstance(text, str):
            return []
        paths = _PATCH_PATH_RE.findall(text)
        paths.extend(_PATCH_MOVE_RE.findall(text))
        return paths

    return []


def evaluate(payload: dict, config: dict, root_str: str | None) -> tuple[bool, str]:
    """Return (allowed, reason)."""
    if not config.get("enabled", True):
        return True, ""
    if not root_str:
        return True, ""

    tool_name = payload.get("tool", "")
    paths = extract_paths(tool_name, payload.get("input"))
    if not paths:
        return True, ""

    root = Path(root_str).resolve()
    allow_outside = config.get("allow_outside", [])

    cwd = os.getcwd()
    for raw in paths:
        resolved = _resolve(raw, cwd)
        if not _allowed(resolved, root, allow_outside):
            return False, (
                f"path '{resolved}' is outside project_root '{root}' "
                f"(tool '{tool_name}')"
            )
    return True, ""


def run(url: str = TABULA_URL) -> None:
    conn = KernelConnection(url)
    conn.send({
        "type": MSG_CONNECT,
        "name": "hook-workspace-boundary",
        "sends": [MSG_HOOK_RESULT],
        "receives": [MSG_HOOK],
        "hooks": [{"event": HOOK_BEFORE_TOOL_CALL, "priority": 90}],
    })
    conn.recv()  # connected

    try:
        while True:
            msg = conn.recv()
            if msg is None:
                break
            if msg.get("type") != MSG_HOOK:
                continue

            hook_id = msg.get("id", "")
            payload = msg.get("payload", {})
            config = load_config()
            allowed, reason = evaluate(payload, config, project_root())

            if allowed:
                conn.send({"type": MSG_HOOK_RESULT, "id": hook_id, "action": HOOK_PASS})
            else:
                conn.send({
                    "type": MSG_HOOK_RESULT,
                    "id": hook_id,
                    "action": HOOK_BLOCK,
                    "reason": reason,
                })
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()


if __name__ == "__main__":
    run()
