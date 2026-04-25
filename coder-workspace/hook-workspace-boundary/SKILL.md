---
name: hook-workspace-boundary
description: "Block file-tool calls whose target path escapes the active project_root."
---

# hook-workspace-boundary

Subscribes to `before_tool_call` and blocks file-tool calls with paths outside the
current project root.

If `TABULA_PROJECT_ROOT` is unset, the hook passes every call (no project context →
no boundary to enforce).

## Enforced tools

For these tools the hook inspects `params.path` and blocks the call when the resolved
absolute path is outside the project root:

- `read`, `write`, `edit`, `multiedit`
- `list_dir`, `glob`, `grep`

For `apply_patch` the hook parses the patch header lines (`*** Add File:`,
`*** Update File:`, `*** Delete File:`, `*** Move to:`) and blocks the call if any
referenced path is outside the project root.

Shell tools (`shell_exec`, `process_spawn`) are **not** policed by this hook — use
`hook-permissions` or `hook-approvals` for command-level rules.

## Configuration

File: `$TABULA_HOME/config/skills/hook-workspace-boundary/config.json`

```json
{
  "enabled": true,
  "allow_outside": ["/tmp", "/private/tmp", "/var/log"]
}
```

- `enabled` (bool, default `true`): turn the hook off without removing it.
- `allow_outside` (list of absolute path prefixes): paths under any of these
  prefixes are allowed even if they live outside the project root. Useful for
  scratch dirs and logs.

Missing / invalid config is equivalent to `{"enabled": true, "allow_outside": []}`.
