---
name: mcp
description: "MCP bridge — connects Tabula to Model Context Protocol servers (filesystem, APIs, DBs). Exposes generic tools (mcp_list_servers, mcp_discover, mcp_list_tools, mcp_call) plus first-class `mcp__<server>__<tool>` tools registered by the distro's boot.py via mcp.register.mcp_tool_entries."
requires-kernel-tools: ["shell_exec"]
tools:
  [
    {
      "name": "mcp_list_servers",
      "description": "List configured MCP servers from config/skills/mcp/servers.json.",
      "params": {},
      "required": []
    },
    {
      "name": "mcp_discover",
      "description": "Connect to all MCP servers and return their tool catalogs keyed by server name.",
      "params": {},
      "required": []
    },
    {
      "name": "mcp_list_tools",
      "description": "List tools exposed by a single MCP server.",
      "params": {
        "server": { "type": "string", "description": "Server name as defined in servers.json." }
      },
      "required": ["server"]
    },
    {
      "name": "mcp_call",
      "description": "Call a tool on an MCP server with JSON arguments. Result is flattened to {text, attachments, isError?}.",
      "params": {
        "server": { "type": "string", "description": "Server name." },
        "tool":   { "type": "string", "description": "Tool name as reported by the server." },
        "args":   { "type": "object", "description": "Tool arguments (object)." }
      },
      "required": ["server", "tool"]
    }
  ]
---

# MCP Bridge

Connects Tabula to [Model Context Protocol](https://modelcontextprotocol.io)
servers (stdio and HTTP transports).

## Two levels of access

1. **Generic tools** — declared in this SKILL.md, always available:
   `mcp_list_servers`, `mcp_discover`, `mcp_list_tools`, `mcp_call`.
   They let a driver introspect and call any MCP tool through a meta-interface.

2. **First-class tools** — discovered at boot and registered with the kernel as
   real tools named `mcp__<server>__<tool>`. Each gets its own JSON-Schema
   params derived from the MCP server's `inputSchema`, so the LLM sees them
   alongside native skills in its tool list.

   The distro's `boot.py` opts in by importing the helper:

   ```python
   from mcp.register import mcp_tool_entries
   tools.extend(mcp_tool_entries(venv_python=VENV_PYTHON))
   ```

   The helper discovers tools from `servers.json`, skips any server/tool whose
   name falls outside `[A-Za-z0-9_]` or contains the `__` separator, and emits
   kernel-format tool entries with `exec` pointing back at this skill.

## Pool daemon

The optional pool daemon (`python3 skills/mcp/run.py pool`) keeps MCP server
processes alive between calls. `run.py` routes through the pool if its URL file
exists and the socket accepts connections; otherwise it falls back to a
short-lived per-call `ClientPool`.

## Config

### Pool settings (`~/.tabula/config/global.toml`)

```toml
[mcp.pool]
url  = ""
host = "0.0.0.0"
port = 0
```

| Key | Type | Default | Env | Aliases |
|---|---|---|---|---|
| `pool.url`  | string | `""` | `TABULA_SKILL_MCP_POOL_URL`  | `TABULA_MCP_POOL_URL`  |
| `pool.host` | string | `0.0.0.0` | `TABULA_SKILL_MCP_POOL_HOST` | `TABULA_MCP_POOL_HOST` |
| `pool.port` | int    | `0` (auto) | `TABULA_SKILL_MCP_POOL_PORT` | `TABULA_MCP_POOL_PORT` |

### Server definitions (`~/.tabula/config/skills/mcp/servers.json`)

```json
{
  "servers": {
    "filesystem": {
      "transport": "stdio",
      "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    },
    "fetch": {
      "transport": "stdio",
      "command": ["uvx", "mcp-server-fetch"]
    },
    "remote-api": {
      "transport": "http",
      "url": "https://api.example.com/mcp",
      "headers": { "Authorization": "Bearer $API_TOKEN" }
    }
  }
}
```

Stdio `command` and HTTP `url`/`headers` support `$VAR` expansion from the
environment.

## Storage

- Server definitions: `~/.tabula/config/skills/mcp/servers.json`
- Pool URL file: `~/.tabula/run/mcp/pool.url`

## Legacy CLI

For debugging and tools that existed before the skill-tool mode:

```bash
python3 skills/mcp/run.py discover
python3 skills/mcp/run.py list filesystem
python3 skills/mcp/run.py call filesystem read_file '{"path": "/etc/hosts"}'
python3 skills/mcp/run.py pool
```

## Skip MCP

Set `TABULA_SKIP_MCP=1` in the environment that runs `boot.py` to skip MCP
discovery entirely (useful for offline boots or test harnesses).
