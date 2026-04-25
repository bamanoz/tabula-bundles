# coder-tasks

Session-scoped todo list for coding agents.

- `todo` — `todowrite`, `todoread`. Session-scoped, persisted to
  `$TABULA_HOME/state/todo/<session>.json`. Survives kernel restarts.

A longer-lived `tasks` queue for batch/background work is out of scope for MVP and
will land in a later phase.
