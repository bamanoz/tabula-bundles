---
name: workspace
description: "Introspect and configure the current project root. Use workspace_info to resolve the active project_root / cwd / git_root. Use workspace_set_root to persist a new project root (applied on next kernel restart)."
tools:
  [
    {
      "name": "workspace_info",
      "description": "Return the current project_root, cwd, git_root (if inside a git repo), and whether cwd is inside project_root.",
      "params": {},
      "required": []
    },
    {
      "name": "workspace_set_root",
      "description": "Persist a new project_root to $TABULA_HOME/config/skills/workspace/root.json. Takes effect on next kernel start. The path is resolved to an absolute path and must exist and be a directory.",
      "params": {
        "path": { "type": "string", "description": "Absolute or relative path to the new project root" }
      },
      "required": ["path"]
    }
  ]
---

# workspace

Project-root introspection and configuration.

## Tools

### workspace_info
No parameters. Returns JSON:

```json
{
  "project_root": "/abs/path/to/repo" ,
  "cwd": "/current/working/dir",
  "in_project_root": true,
  "git_root": "/abs/path/to/repo",
  "relative_cwd": "subdir/a"
}
```

`project_root` comes from the `TABULA_PROJECT_ROOT` environment variable, which the
kernel populates from its `Hub.ProjectRoot` (also exposed via `init.meta.project_root`).
`git_root` is resolved by running `git rev-parse --show-toplevel`; `null` if not in a
git working tree. `relative_cwd` is `cwd` relative to `project_root`, or `null` if cwd
is outside.

### workspace_set_root
Writes the given absolute path to
`$TABULA_HOME/config/skills/workspace/root.json` as `{"project_root": "/abs"}`.

The kernel reads `TABULA_PROJECT_ROOT` at boot, so this change becomes active on the
next kernel restart. A full in-session dynamic update is out of scope for MVP — it
would require a kernel-level message to mutate `Hub.ProjectRoot` at runtime.
