# coder-git

First-class git tools for coding agents. Each tool returns JSON with structured
fields (files touched, parsed diff hunks, branch lists) so higher-level UIs can
render diffs and status without re-shelling out.

### Safety rails

- **No auto-push.** There is no `git_push` tool. Pushes are the user's decision
  and are issued via `shell_exec` with explicit approval.
- **No force operations.** No `git_reset --hard`, no force-checkout, no
  rewriting history.
- **No credential management.** All auth relies on the user's existing git
  configuration (ssh-agent / credential helper).

The tools are thin wrappers around `git` and assume the binary is on `PATH`.
