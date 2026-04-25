#!/usr/bin/env python3
"""
MCP bridge skill for Tabula.

Two call modes:

1. Legacy CLI subcommands (backward compat):
     run.py discover
     run.py list <server>
     run.py call <server> <tool> [args_json]
     run.py pool

2. Skill-tool mode (first-class tool registration):
     run.py tool mcp_list_servers      < stdin = {}
     run.py tool mcp_discover          < stdin = {}
     run.py tool mcp_list_tools        < stdin = {"server": "<name>"}
     run.py tool mcp_call              < stdin = {"server": "...", "tool": "...", "args": {...}}
     run.py tool mcp__<server>__<tool> < stdin = {"<arg>": ...}

The `mcp__<server>__<tool>` names are the first-class names that distro
boot.py emits (via register.mcp_tool_entries) so that LLM drivers see MCP
tools alongside native skills.

When the pool daemon is running, calls route through it; otherwise falls back
to a short-lived direct ClientPool.
"""

import argparse
import json
import os
import sys

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
TABULA_HOME = os.environ.get("TABULA_HOME", os.path.expanduser("~/.tabula"))
SKILLS_ROOT = os.path.join(TABULA_HOME, "skills")
DISTRIB_SKILLS_ROOT = os.path.join(TABULA_HOME, "distrib", "main", "skills")
for p in (SKILLS_ROOT, DISTRIB_SKILLS_ROOT, os.path.dirname(SKILL_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mcp.daemon import pool_is_running, pool_request  # noqa: E402
from mcp.pool import ClientPool  # noqa: E402
from mcp.client import MCPError  # noqa: E402

FIRST_CLASS_PREFIX = "mcp__"
FIRST_CLASS_SEP = "__"


# ── helpers ────────────────────────────────────────────────────────────────


def _err(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


def _via_pool(req: dict) -> dict | None:
    if not pool_is_running():
        return None
    try:
        return pool_request(req)
    except Exception:
        return None


def _do_call(server: str, tool: str, args: dict) -> dict:
    resp = _via_pool({"method": "call", "server": server, "tool": tool, "args": args})
    if resp is not None:
        if not resp["ok"]:
            raise MCPError(-1, resp["error"])
        return resp["result"]
    pool = ClientPool()
    try:
        client = pool.get(server)
        return client.call_tool(tool, args)
    finally:
        pool.close_all()


def _do_list(server: str) -> list[dict]:
    resp = _via_pool({"method": "list_tools", "server": server})
    if resp is not None:
        if not resp["ok"]:
            raise MCPError(-1, resp["error"])
        return resp["result"]
    pool = ClientPool()
    try:
        return pool.get(server).list_tools()
    finally:
        pool.close_all()


def _do_discover() -> dict[str, list[dict]]:
    resp = _via_pool({"method": "discover"})
    if resp is not None:
        if not resp["ok"]:
            raise MCPError(-1, resp["error"])
        return resp["result"]
    pool = ClientPool()
    try:
        return pool.discover_all()
    finally:
        pool.close_all()


def _flatten_content(result: dict) -> dict:
    """Flatten MCP tool-call result to a text-centric payload for the driver."""
    text_parts: list[str] = []
    attachments: list[dict] = []
    for content in result.get("content", []):
        ctype = content.get("type", "text")
        if ctype == "text":
            text_parts.append(content.get("text", ""))
        elif ctype == "image":
            attachments.append({
                "type": "image",
                "mimeType": content.get("mimeType"),
                "data_length": len(content.get("data", "")),
            })
        elif ctype == "resource":
            res = content.get("resource", {})
            attachments.append({
                "type": "resource",
                "uri": res.get("uri"),
                "text": res.get("text"),
            })
        else:
            attachments.append(content)
    out: dict = {"text": "\n".join(p for p in text_parts if p)}
    if attachments:
        out["attachments"] = attachments
    if result.get("isError"):
        out["isError"] = True
    return out


# ── skill-tool handlers ────────────────────────────────────────────────────


def tool_mcp_list_servers(_: dict) -> str:
    pool = ClientPool()
    try:
        return json.dumps({"servers": pool.server_names()}, ensure_ascii=False)
    finally:
        pool.close_all()


def tool_mcp_discover(_: dict) -> str:
    try:
        return json.dumps(_do_discover(), ensure_ascii=False)
    except Exception as exc:
        return _err(str(exc))


def tool_mcp_list_tools(params: dict) -> str:
    server = params.get("server")
    if not isinstance(server, str) or not server:
        return _err("server must be a non-empty string")
    try:
        return json.dumps({"server": server, "tools": _do_list(server)}, ensure_ascii=False)
    except Exception as exc:
        return _err(str(exc))


def tool_mcp_call(params: dict) -> str:
    server = params.get("server")
    tool = params.get("tool")
    args = params.get("args") or {}
    if not isinstance(server, str) or not server:
        return _err("server must be a non-empty string")
    if not isinstance(tool, str) or not tool:
        return _err("tool must be a non-empty string")
    if not isinstance(args, dict):
        return _err("args must be a JSON object")
    try:
        result = _do_call(server, tool, args)
        return json.dumps(_flatten_content(result), ensure_ascii=False)
    except Exception as exc:
        return _err(str(exc))


STATIC_TOOLS = {
    "mcp_list_servers": tool_mcp_list_servers,
    "mcp_discover": tool_mcp_discover,
    "mcp_list_tools": tool_mcp_list_tools,
    "mcp_call": tool_mcp_call,
}


def _dispatch_first_class(tool_name: str, params: dict) -> str:
    """Handle mcp__<server>__<tool> first-class names."""
    body = tool_name[len(FIRST_CLASS_PREFIX):]
    idx = body.find(FIRST_CLASS_SEP)
    if idx < 0:
        return _err(f"invalid first-class MCP tool name: {tool_name!r}")
    server = body[:idx]
    tool = body[idx + len(FIRST_CLASS_SEP):]
    if not server or not tool:
        return _err(f"invalid first-class MCP tool name: {tool_name!r}")
    if not isinstance(params, dict):
        return _err("tool input must be a JSON object")
    try:
        result = _do_call(server, tool, params)
        return json.dumps(_flatten_content(result), ensure_ascii=False)
    except Exception as exc:
        return _err(str(exc))


def _handle_tool(tool_name: str) -> int:
    try:
        raw = sys.stdin.read()
        params = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        print(_err(f"invalid JSON input: {exc}"))
        return 0
    if not isinstance(params, dict):
        print(_err("tool input must be a JSON object"))
        return 0

    handler = STATIC_TOOLS.get(tool_name)
    if handler is not None:
        print(handler(params))
        return 0
    if tool_name.startswith(FIRST_CLASS_PREFIX):
        print(_dispatch_first_class(tool_name, params))
        return 0
    print(f"ERROR: unknown tool {tool_name}", file=sys.stderr)
    return 1


# ── legacy CLI ─────────────────────────────────────────────────────────────


def cmd_discover(_args):
    try:
        tools = _do_discover()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    json.dump(tools, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def cmd_list(args):
    try:
        tools = _do_list(args.server)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    for tool in tools:
        schema = tool.get("inputSchema", {})
        params = schema.get("properties", {})
        param_str = ", ".join(f"{k}: {v.get('type', 'any')}" for k, v in params.items())
        print(f"  {tool['name']}({param_str}) — {tool.get('description', '')}")


def cmd_call(args):
    arguments = json.loads(args.args) if args.args else {}
    try:
        result = _do_call(args.server, args.tool, arguments)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    for content in result.get("content", []):
        ctype = content.get("type", "text")
        if ctype == "text":
            print(content.get("text", ""))
        elif ctype == "image":
            mime = content.get("mimeType", "unknown")
            data_len = len(content.get("data", ""))
            print(f"[image: {mime}, {data_len} bytes base64]")
        elif ctype == "resource":
            res = content.get("resource", {})
            print(f"[resource: {res.get('uri', 'unknown')}]")
            if "text" in res:
                print(res["text"])
        else:
            print(json.dumps(content, ensure_ascii=False))


def cmd_pool(_args):
    from mcp.daemon import run_daemon
    run_daemon()


def main():
    # Skill-tool mode: "run.py tool <tool_name>" — reads JSON params from stdin.
    if len(sys.argv) >= 3 and sys.argv[1] == "tool":
        sys.exit(_handle_tool(sys.argv[2]))

    parser = argparse.ArgumentParser(description="MCP bridge for Tabula")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("discover", help="Discover all MCP tools")
    p_list = sub.add_parser("list", help="List tools for a server")
    p_list.add_argument("server")
    p_call = sub.add_parser("call", help="Call an MCP tool")
    p_call.add_argument("server")
    p_call.add_argument("tool")
    p_call.add_argument("args", nargs="?", default="{}")
    sub.add_parser("pool", help="Start persistent MCP server pool")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    {
        "discover": cmd_discover,
        "list": cmd_list,
        "call": cmd_call,
        "pool": cmd_pool,
    }[args.command](args)


if __name__ == "__main__":
    main()
