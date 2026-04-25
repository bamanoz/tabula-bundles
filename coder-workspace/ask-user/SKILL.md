---
name: ask-user
description: "Ask the user a question with multiple choice options. Blocks until the user responds. Use when you need clarification or user decision to proceed."
tools:
  [
    {
      "name": "ask_user",
      "description": "Ask the user a question and wait for their choice. Returns the selected option.",
      "params": {
        "question": { "type": "string", "description": "The question to ask the user" },
        "options": {
          "type": "array",
          "items": { "type": "string" },
          "description": "List of options for the user to choose from (2-5 options)"
        }
      },
      "required": ["question", "options"]
    }
  ]
---

# ask-user

Interactive user prompt tool. Allows agents to pause and ask the user a question
with predefined options, then continue based on the user's choice.

## Tool: ask_user

**Parameters:**
- `question` (string, required): The question to display to the user
- `options` (array of strings, required): 2-5 choices for the user

**Returns:**
```json
{
  "choice": "selected option text",
  "index": 0
}
```

## Protocol

When invoked, the skill:
1. Connects to kernel WebSocket
2. Sends `MSG_STATUS` with `meta.ask_request` containing `{id, question, options}`
3. TUI displays an interactive prompt
4. User selects an option
5. TUI sends `MSG_MESSAGE` with `meta.ask_response` containing `{id, choice, index}`
6. Skill receives response via `receives_global`
7. Returns tool result with the user's choice

## Example

```
tool_use: ask_user
input: {
  "question": "Which database should we use?",
  "options": ["PostgreSQL", "MySQL", "SQLite"]
}

# User sees prompt, selects "PostgreSQL"

tool_result: {"choice": "PostgreSQL", "index": 0}
```
