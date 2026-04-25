---
name: todo
description: "Session-scoped todo list. Call todoread to see current tasks; call todowrite to replace the full list. Use it to plan multi-step work and mark steps done as you go."
tools:
  [
    {
      "name": "todoread",
      "description": "Return the current session's todo list.",
      "params": {},
      "required": []
    },
    {
      "name": "todowrite",
      "description": "Replace the entire todo list for the current session. Takes an array of items; each item has content (string) and status (pending | in_progress | completed).",
      "params": {
        "items": {
          "type": "array",
          "description": "Full replacement list",
          "items": {
            "type": "object",
            "properties": {
              "content": { "type": "string", "description": "Short task description" },
              "status": { "type": "string", "description": "pending, in_progress, or completed" },
              "active_form": { "type": "string", "description": "Present-continuous form shown while in progress" }
            },
            "required": ["content", "status"]
          }
        }
      },
      "required": ["items"]
    }
  ]
---

# todo

Session-scoped todo list. The full list is replaced on every `todowrite`; there is
no partial update. Mark items `in_progress` when you start them and `completed`
when done — the distro prompt should tell the driver to keep exactly one item
`in_progress` at a time.

## Storage

- File: `$TABULA_HOME/state/todo/<session>.json`
- Schema:
  ```json
  {
    "version": 1,
    "session": "<session-id>",
    "updated_at": "2026-04-22T19:00:00Z",
    "items": [
      {"content": "plan", "status": "completed"},
      {"content": "impl", "status": "in_progress", "active_form": "implementing"}
    ]
  }
  ```

The session id is read from `$TABULA_SESSION` (set by the kernel when invoking
skill tools). If unset, the list falls back to a shared `_default.json`.
