# coder-workspace

Workspace primitives for coding agents:

- `workspace` — tools to introspect and configure the current project root.
- `hook-workspace-boundary` — blocks file-tool calls that escape the project root.
- `hook-approvals` — file-based allow/deny rules with path/command pattern matching.
  Interactive approval flow (allow once / deny once) plugs in later via the TUI gateway.

The bundle assumes the kernel exposes the active project root via the `init.meta.project_root`
field and the `TABULA_PROJECT_ROOT` environment variable.
