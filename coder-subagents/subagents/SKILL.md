---
name: subagents
description: "Spawn, steer, list, wait on, and kill typed subagents. Call subagent_spawn with a type preset (explore/plan/review/fix/general) and a task; use subagent_wait to collect the result."
tools:
  [
    {
      "name": "subagent_spawn",
      "description": "Spawn a subagent of the given type with a task. Returns immediately with the subagent id. Use subagent_wait to collect the final result.",
      "params": {
        "type": { "type": "string", "description": "One of the type presets in types/ (explore, plan, review, fix, general)." },
        "task": { "type": "string", "description": "Initial task prompt for the subagent." },
        "id": { "type": "string", "description": "Optional explicit id; default: auto-generated short uuid." },
        "model": { "type": "string", "description": "Optional provider model override (e.g. gpt-5.4)." },
        "cwd": { "type": "string", "description": "Working directory for the subagent; must be inside the project root if boundary hook is active." },
        "allowed_tools": { "type": "array", "items": { "type": "string" }, "description": "Whitelist of tool names; overrides the type preset default." },
        "max_turns": { "type": "integer", "description": "Max LLM turns; overrides the type preset default." },
        "timeout": { "type": "integer", "description": "Idle timeout in seconds; 0 means oneshot." },
        "mode": { "type": "string", "description": "sync (blocks until finished) or async (returns id immediately). Default: async." }
      },
      "required": ["type", "task"]
    },
    {
      "name": "subagent_send",
      "description": "Send a follow-up message into an active subagent session.",
      "params": {
        "id": { "type": "string", "description": "Subagent id returned by subagent_spawn." },
        "message": { "type": "string", "description": "Message text to deliver to the subagent." }
      },
      "required": ["id", "message"]
    },
    {
      "name": "subagent_steer",
      "description": "Inject a steering instruction into an active subagent mid-task. Same wire shape as subagent_send but semantically a user-priority nudge.",
      "params": {
        "id": { "type": "string", "description": "Subagent id." },
        "instruction": { "type": "string", "description": "Steering directive (short imperative)." }
      },
      "required": ["id", "instruction"]
    },
    {
      "name": "subagent_wait",
      "description": "Block until the subagent finishes, returns its recorded result, or times out.",
      "params": {
        "id": { "type": "string", "description": "Subagent id." },
        "timeout": { "type": "integer", "description": "Seconds to wait. Default: 120. Pass 0 for non-blocking poll." }
      },
      "required": ["id"]
    },
    {
      "name": "subagent_list",
      "description": "List subagents for the current parent session (id, type, status, pid, timestamps).",
      "params": {
        "parent_session": { "type": "string", "description": "Filter by parent session; default: current TABULA_SESSION." },
        "status": { "type": "string", "description": "Filter by status (running, completed, failed, killed)." }
      },
      "required": []
    },
    {
      "name": "subagent_kill",
      "description": "Terminate a running subagent (SIGTERM, SIGKILL after grace).",
      "params": {
        "id": { "type": "string", "description": "Subagent id." }
      },
      "required": ["id"]
    }
  ]
---

# subagents

Managed subagent orchestration. Each subagent runs in its own kernel session,
under a typed preset that defines provider, model, allowed tools, turn budget,
and a system-prompt suffix.

## Lifecycle

1. `subagent_spawn` resolves the type preset, builds the subagent command
   (`drivers/subagent/run.py --provider <provider> ...`), spawns the process, and writes
   a registry entry at `$TABULA_HOME/state/subagents/<id>.json`.
2. The subagent connects to the kernel, joins session `subagent-<id>`, runs the
   task, and (when the process exits) leaves its final output in
   `$TABULA_HOME/state/subagents/<id>.result.txt` if configured.
3. `subagent_wait` polls the registry entry / process liveness.
4. `subagent_send` / `subagent_steer` deliver follow-up messages via the kernel
   WebSocket.
5. `subagent_kill` terminates the process and marks the registry `killed`.

## Storage

- `$TABULA_HOME/state/subagents/<id>.json` — registry entry.
- `$TABULA_HOME/state/subagents/<id>.result.txt` — captured final output.
- `$TABULA_HOME/logs/subagents/<id>.log` — stderr capture.

## Types

Defined under `skills/_subagent_types/*.toml`. MVP set: `explore`, `plan`,
`review`, `fix`, `general`. Each preset is resolved by file name (e.g.
type="explore" → `_subagent_types/explore.toml`).

## Notes

- `allowed_tools` is recorded in the registry for observability. Enforcement
  is expected to hook into `coder-workspace/hook-approvals` — not yet wired.
- `mode=sync` blocks until completion or timeout; default is `async`.
- `subagent_send` / `subagent_steer` require an active process.
