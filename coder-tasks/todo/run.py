#!/usr/bin/env python3
"""todo skill — session-scoped todo list with on-disk persistence."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = os.environ.get("TABULA_HOME", os.path.expanduser("~/.tabula"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from skills._pylib.paths import skill_state_dir, ensure_parent


SCHEMA_VERSION = 1
ALLOWED_STATUSES = {"pending", "in_progress", "completed"}
_SESSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class ToolError(Exception):
    pass


def _err(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


def _session_id() -> str:
    raw = os.environ.get("TABULA_SESSION", "").strip()
    if not raw:
        return "_default"
    # Guard against path traversal in filename.
    if not _SESSION_RE.match(raw):
        return "_default"
    return raw


def _state_file(session: str) -> Path:
    return skill_state_dir("todo") / f"{session}.json"


def _read(session: str) -> dict:
    path = _state_file(session)
    if not path.is_file():
        return {
            "version": SCHEMA_VERSION,
            "session": session,
            "updated_at": None,
            "items": [],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ToolError(f"invalid todo state file at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ToolError(f"invalid todo state at {path}: not a JSON object")
    items = data.get("items")
    if not isinstance(items, list):
        items = []
    data["items"] = items
    data.setdefault("version", SCHEMA_VERSION)
    data.setdefault("session", session)
    return data


def _write(session: str, items: list[dict]) -> dict:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    data = {
        "version": SCHEMA_VERSION,
        "session": session,
        "updated_at": now,
        "items": items,
    }
    path = ensure_parent(_state_file(session))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return data


def _normalize_item(raw, idx: int) -> dict:
    if not isinstance(raw, dict):
        raise ToolError(f"items[{idx}] must be an object")
    content = raw.get("content")
    status = raw.get("status")
    if not isinstance(content, str) or not content.strip():
        raise ToolError(f"items[{idx}].content must be a non-empty string")
    if not isinstance(status, str) or status not in ALLOWED_STATUSES:
        raise ToolError(
            f"items[{idx}].status must be one of {sorted(ALLOWED_STATUSES)}"
        )
    item: dict = {"content": content.strip(), "status": status}
    active = raw.get("active_form")
    if isinstance(active, str) and active.strip():
        item["active_form"] = active.strip()
    return item


def todoread(_: dict) -> str:
    try:
        session = _session_id()
        data = _read(session)
        return json.dumps(data, ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))


def todowrite(params: dict) -> str:
    try:
        items_raw = params.get("items")
        if not isinstance(items_raw, list):
            raise ToolError("items must be an array")
        items = [_normalize_item(x, i) for i, x in enumerate(items_raw)]

        # At most one in_progress — warn by rejecting so the driver fixes its plan.
        in_progress = sum(1 for it in items if it["status"] == "in_progress")
        if in_progress > 1:
            raise ToolError(
                "at most one item can be in_progress at a time; mark the rest pending or completed"
            )

        session = _session_id()
        data = _write(session, items)
        return json.dumps(data, ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))


TOOLS = {
    "todoread": todoread,
    "todowrite": todowrite,
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
            print(_err(f"invalid JSON input: {exc}"))
            sys.exit(0)
        if not isinstance(params, dict):
            print(_err("tool input must be a JSON object"))
            sys.exit(0)
        print(handler(params))
        return

    print("Usage: run.py tool <tool_name>", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
