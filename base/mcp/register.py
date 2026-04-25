"""
Helper for distro boot scripts: discovers MCP tools at boot time and returns
kernel-format tool entries so they register as first-class tools.

Usage from boot.py:

    from mcp.register import mcp_tool_entries
    tools.extend(mcp_tool_entries(venv_python=VENV_PYTHON))

Each returned entry has the shape:

    {
      "name": "mcp__<server>__<tool>",
      "description": "...",
      "params": { ... kernel-format param schema ... },
      "required": [...],
      "exec": "<venv_python> skills/mcp/run.py tool mcp__<server>__<tool>"
    }

Servers/tools whose names can't be safely encoded (contain the separator `__`
or characters outside [A-Za-z0-9_]) are skipped with a stderr warning.
"""

from __future__ import annotations

import os
import re
import sys

SEP = "__"
PREFIX = "mcp__"
NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _safe_name(s: str) -> bool:
    return bool(NAME_RE.match(s)) and SEP not in s


def _convert_schema(input_schema: dict | None) -> tuple[dict, list[str]]:
    """Convert an MCP `inputSchema` (JSON Schema) to kernel tool param format."""
    if not isinstance(input_schema, dict):
        return {}, []
    properties = input_schema.get("properties") or {}
    required = input_schema.get("required") or []
    if not isinstance(properties, dict):
        properties = {}
    if not isinstance(required, list):
        required = []
    params: dict = {}
    for key, spec in properties.items():
        if not isinstance(spec, dict):
            continue
        entry: dict = {}
        if "type" in spec:
            entry["type"] = spec["type"]
        if "description" in spec:
            entry["description"] = spec["description"]
        if "enum" in spec:
            entry["enum"] = spec["enum"]
        if "items" in spec:
            entry["items"] = spec["items"]
        params[key] = entry
    return params, [r for r in required if isinstance(r, str)]


def mcp_tool_entries(
    *,
    venv_python: str,
    skill_rel_path: str = "mcp",
    discover_fn=None,
) -> list[dict]:
    """Discover MCP tools and emit first-class kernel tool entries.

    `venv_python` — absolute path to the Python used to run skills.
    `skill_rel_path` — where mcp/run.py lives relative to TABULA_HOME/skills.
    `discover_fn` — optional injection point for tests; defaults to live call.
    """
    if os.environ.get("TABULA_SKIP_MCP"):
        return []

    if discover_fn is None:
        # Import lazily so register.py can be imported even when the pool
        # daemon stack has dependency issues (e.g. missing `requests`).
        try:
            from mcp.run import _do_discover as live_discover  # type: ignore
            discover_fn = live_discover
        except Exception as exc:
            print(f"warning: MCP discover unavailable: {exc}", file=sys.stderr)
            return []

    try:
        tools_by_server = discover_fn()
    except Exception as exc:
        print(f"warning: MCP discover failed: {exc}", file=sys.stderr)
        return []

    entries: list[dict] = []
    for server in sorted(tools_by_server or {}):
        if not _safe_name(server):
            print(
                f"warning: MCP server {server!r} has an unsafe name; skipping first-class registration",
                file=sys.stderr,
            )
            continue
        for tool in tools_by_server[server] or []:
            tool_name = tool.get("name", "")
            if not isinstance(tool_name, str) or not _safe_name(tool_name):
                print(
                    f"warning: MCP tool {server}/{tool_name!r} has an unsafe name; skipping",
                    file=sys.stderr,
                )
                continue
            first_class = f"{PREFIX}{server}{SEP}{tool_name}"
            params, required = _convert_schema(tool.get("inputSchema"))
            description = tool.get("description") or f"MCP tool {server}.{tool_name}"
            entries.append({
                "name": first_class,
                "description": description,
                "params": params,
                "required": required,
                "exec": f"{venv_python} skills/{skill_rel_path}/run.py tool {first_class}",
            })
    return entries
