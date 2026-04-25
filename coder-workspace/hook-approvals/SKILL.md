---
name: hook-approvals
description: "Allow/deny tool calls with pattern rules on path, command, or tool name. File-based persistence; interactive allow-once / deny-once will plug into the TUI gateway."
---

# hook-approvals

Pattern-based approval layer on top of tool calls. Subscribes to `before_tool_call`
with priority 80 (lower than `hook-permissions`, so kernel-level bans still fire
first).

This is the MVP file-based layer: rules live on disk and resolve to either
`allow_always` or `deny_always`. Runtime allow-once / deny-once responses require
interactive feedback from the gateway and are added in Phase 5 (TUI).

## Configuration

File: `$TABULA_HOME/config/skills/hook-approvals/rules.json`

```json
{
  "rules": [
    {"tool": "write", "path": "docs/**", "effect": "allow_always"},
    {"tool": "shell_exec", "command": "git push *--force*", "effect": "deny_always"},
    {"tool": "shell_exec", "command": "git push origin *", "effect": "allow_always"},
    {"tool": "*", "effect": "allow_always"}
  ]
}
```

### Rule fields

- `tool` (required): fnmatch pattern against the tool name (`*`, `write*`, `git_*`, etc.).
- `path` (optional): fnmatch pattern against `params.path` for file tools, or against
  each path extracted from `params.patch_text` for `apply_patch`.
- `command` (optional): fnmatch pattern against `params.command` for `shell_exec` and
  `process_spawn`.
- `effect` (required): `allow_always` or `deny_always`.

### Precedence

1. A rule with `path` or `command` is more specific than a rule with only `tool`.
2. Within the same specificity tier, deny wins.
3. No matching rule → pass.

Rules are re-read on every hook call, so edits take effect immediately.
