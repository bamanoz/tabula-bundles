#!/usr/bin/env python3
"""ask-user skill — interactive user prompt tool.

Allows agents to ask the user a question with multiple choice options.
The skill connects to the kernel, sends an ask_request to the TUI,
waits for the user's response, and returns it as the tool result.
"""

from __future__ import annotations

import json
import os
import sys
import uuid

ROOT = os.environ.get("TABULA_HOME", os.path.expanduser("~/.tabula"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from skills._pylib.kernel_client import KernelConnection
from skills._pylib.protocol import (
    MSG_CONNECT, MSG_STATUS,
)

TABULA_URL = os.environ.get("TABULA_URL", "ws://localhost:8089/ws")
TABULA_SESSION = os.environ.get("TABULA_SESSION", "")


def ask_user(params: dict) -> str:
    """Ask user a question and return their choice."""
    question = params.get("question", "")
    options = params.get("options", [])

    if not question:
        return json.dumps({"error": "question is required"})
    if not isinstance(options, list) or len(options) < 2:
        return json.dumps({"error": "options must be a list with at least 2 items"})
    if len(options) > 5:
        return json.dumps({"error": "options must have at most 5 items"})

    # Generate unique request ID
    request_id = str(uuid.uuid4())[:8]

    # Connect to kernel
    conn = KernelConnection(TABULA_URL)
    conn.send({
        "type": MSG_CONNECT,
        "name": f"ask-user-{request_id}",
        "sends": [MSG_STATUS],
        "receives": [],
        "receives_global": [MSG_STATUS],
    })
    resp = conn.recv()
    if resp is None or resp.get("type") != "connected":
        conn.close()
        return json.dumps({"error": "failed to connect to kernel"})

    # Join the session so our MSG_STATUS reaches the TUI
    if TABULA_SESSION:
        conn.send({"type": "join", "session": TABULA_SESSION})
        resp = conn.recv()
        if resp is None or resp.get("type") != "joined":
            conn.close()
            return json.dumps({"error": "failed to join session"})

    # Send ask_request to TUI via MSG_STATUS
    conn.send({
        "type": MSG_STATUS,
        "text": "",
        "meta": {
            "ask_request": {
                "id": request_id,
                "question": question,
                "options": options,
            }
        },
    })

    # Wait for ask_response
    try:
        while True:
            msg = conn.recv(timeout=300)  # 5 minute timeout
            if msg is None:
                conn.close()
                return json.dumps({"error": "connection closed while waiting for response"})

            if msg.get("type") != MSG_STATUS:
                continue

            meta = msg.get("meta")
            if not isinstance(meta, dict):
                continue

            ask_response = meta.get("ask_response")
            if not isinstance(ask_response, dict):
                continue

            if ask_response.get("id") != request_id:
                continue

            # Got our response
            choice = ask_response.get("choice", "")
            index = ask_response.get("index", -1)
            conn.close()
            return json.dumps({"choice": choice, "index": index})

    except TimeoutError:
        conn.close()
        return json.dumps({"error": "timeout waiting for user response"})
    except Exception as exc:
        conn.close()
        return json.dumps({"error": f"unexpected error: {exc}"})


TOOLS = {
    "ask_user": ask_user,
}


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "tool":
        tool_name = sys.argv[2]
        handler = TOOLS.get(tool_name)
        if not handler:
            print(f"ERROR: unknown tool {tool_name}", file=sys.stderr)
            sys.exit(1)

        try:
            params = json.load(sys.stdin)
        except json.JSONDecodeError as exc:
            print(json.dumps({"error": f"invalid JSON input: {exc}"}))
            sys.exit(0)

        if not isinstance(params, dict):
            print(json.dumps({"error": "tool input must be a JSON object"}))
            sys.exit(0)

        print(handler(params))
        return

    print("Usage: run.py tool <tool_name>", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
