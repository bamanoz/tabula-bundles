#!/usr/bin/env python3
"""workspace skill — introspect and configure the project root."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = os.environ.get("TABULA_HOME", os.path.expanduser("~/.tabula"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from skills._pylib.paths import skill_config_dir, ensure_parent


def _project_root() -> str | None:
    value = os.environ.get("TABULA_PROJECT_ROOT", "").strip()
    return value or None


def _git_root(cwd: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    path = out.stdout.strip()
    return path or None


def _relative_to(child: str, parent: str | None) -> str | None:
    if not parent:
        return None
    try:
        return str(Path(child).resolve().relative_to(Path(parent).resolve()))
    except ValueError:
        return None


def _inside(child: str, parent: str | None) -> bool:
    if not parent:
        return False
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def workspace_info(_: dict) -> str:
    project_root = _project_root()
    cwd = os.getcwd()
    git_root = _git_root(cwd)
    result = {
        "project_root": project_root,
        "cwd": cwd,
        "in_project_root": _inside(cwd, project_root),
        "git_root": git_root,
        "relative_cwd": _relative_to(cwd, project_root),
    }
    return json.dumps(result, ensure_ascii=False)


def workspace_set_root(params: dict) -> str:
    raw = params.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return json.dumps({"error": "path must be a non-empty string"})
    resolved = Path(os.path.expanduser(raw)).resolve()
    if not resolved.exists():
        return json.dumps({"error": f"path does not exist: {resolved}"})
    if not resolved.is_dir():
        return json.dumps({"error": f"path is not a directory: {resolved}"})

    target = skill_config_dir("workspace") / "root.json"
    ensure_parent(target)
    payload = {"project_root": str(resolved)}
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)

    return json.dumps({
        "project_root": str(resolved),
        "config_file": str(target),
        "note": "takes effect on next kernel restart",
    }, ensure_ascii=False)


TOOLS = {
    "workspace_info": workspace_info,
    "workspace_set_root": workspace_set_root,
}


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "tool":
        tool_name = sys.argv[2]
        handler = TOOLS.get(tool_name)
        if not handler:
            print(f"ERROR: unknown tool {tool_name}", file=sys.stderr)
            sys.exit(1)

        try:
            params = json.load(sys.stdin)
        except json.JSONDecodeError as exc:
            print(json.dumps({"error": f"invalid JSON input: {exc}"}))
            sys.exit(0)

        if not isinstance(params, dict):
            print(json.dumps({"error": "tool input must be a JSON object"}))
            sys.exit(0)

        print(handler(params))
        return

    print("Usage: run.py tool <tool_name>", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
