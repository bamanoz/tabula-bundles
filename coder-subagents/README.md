# coder-subagents

First-class subagent orchestration for coding distros.

Replaces the simple `process_spawn`-based subagent flow used by `familiar` with
a managed registry and richer lifecycle:

- `subagent_spawn` — spawn a typed subagent (`explore`, `plan`, `review`, `fix`,
  `general`) backed by the unified `drivers/subagent` runner.
- `subagent_send` — push a follow-up message into an active subagent session.
- `subagent_steer` — inject a new user message mid-task (first-class steering).
- `subagent_wait` — block until a subagent finishes (or timeout).
- `subagent_list` — list active/completed subagents for the current session.
- `subagent_kill` — terminate an active subagent.

## Registry

Subagent state lives in `$TABULA_HOME/state/subagents/<id>.json` and survives
kernel restarts. Fields: `id`, `parent_session`, `session`, `type`, `provider`,
`model`, `pid`, `status`, `cmd`, `allowed_tools`, `cwd`, `task`, timestamps,
`result_file`.

## Types

Type presets live in `skills/_subagent_types/*.toml`. They define
provider, model, allowed tool whitelist, turn budget, and the system-prompt
suffix used when spawning.
