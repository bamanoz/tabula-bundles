#!/usr/bin/env python3
"""hook-approvals — pattern-based allow/deny for tool calls (file-based MVP)."""

from __future__ import annotations

import json
import os
import re
import sys
from fnmatch import fnmatch

ROOT = os.environ.get("TABULA_HOME", os.path.expanduser("~/.tabula"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from skills._pylib.paths import skill_config_dir, skill_state_dir
from skills._pylib.kernel_client import KernelConnection
from skills._pylib.protocol import (
    MSG_CONNECT, MSG_HOOK, MSG_HOOK_RESULT, MSG_MESSAGE,
    HOOK_PASS, HOOK_BLOCK, HOOK_MODIFY,
    HOOK_BEFORE_TOOL_CALL, TOOL_SHELL_EXEC, TOOL_PROCESS_SPAWN,
)

TABULA_URL = os.environ.get("TABULA_URL", "ws://localhost:8089/ws")
RULES_FILE = skill_config_dir("hook-approvals") / "rules.json"
SUBAGENTS_STATE_DIR = skill_state_dir("subagents")
_SUBAGENT_SESSION_RE = re.compile(r"^subagent-(.+)$")

ALLOW = "allow_always"
DENY = "deny_always"

PATH_TOOLS = {"read", "write", "edit", "multiedit", "list_dir", "glob", "grep"}
_PATCH_PATH_RE = re.compile(
    r"^\*\*\*\s+(?:Add|Update|Delete)\s+File:\s*(.+?)\s*$",
    re.MULTILINE,
)


def load_rules() -> list[dict]:
    if not RULES_FILE.is_file():
        return []
    try:
        data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"hook-approvals: invalid rules: {exc}", file=sys.stderr)
        return []
    if not isinstance(data, dict):
        return []
    rules = data.get("rules", [])
    if not isinstance(rules, list):
        return []
    out = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        if "tool" not in r or "effect" not in r:
            continue
        if r["effect"] not in (ALLOW, DENY):
            continue
        out.append(r)
    return out


def _extract_input(payload: dict) -> dict:
    raw = payload.get("input")
    if raw is None:
        return {}
    try:
        inp = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return {}
    return inp if isinstance(inp, dict) else {}


def _extract_paths(tool_name: str, inp: dict) -> list[str]:
    if tool_name in PATH_TOOLS:
        p = inp.get("path")
        return [p] if isinstance(p, str) and p.strip() else []
    if tool_name == "apply_patch":
        text = inp.get("patch_text")
        if isinstance(text, str):
            return _PATCH_PATH_RE.findall(text)
    return []


def _extract_command(tool_name: str, inp: dict) -> str:
    if tool_name not in (TOOL_SHELL_EXEC, TOOL_PROCESS_SPAWN):
        return ""
    cmd = inp.get("command")
    return cmd if isinstance(cmd, str) else ""


def _rule_matches(rule: dict, tool_name: str, paths: list[str], command: str) -> bool:
    if not fnmatch(tool_name, rule["tool"]):
        return False
    rule_path = rule.get("path")
    rule_cmd = rule.get("command")

    if rule_path:
        if not paths:
            return False
        if not any(fnmatch(p, rule_path) for p in paths):
            return False
    if rule_cmd:
        if not command:
            return False
        if not fnmatch(command, rule_cmd):
            return False
    return True


def _rule_specificity(rule: dict) -> int:
    # 0 = tool-only, 1 = tool + path/command.
    return 1 if (rule.get("path") or rule.get("command")) else 0


def evaluate(rules: list[dict], payload: dict) -> tuple[str | None, dict | None]:
    """Return (effect, matching_rule). None effect = pass."""
    tool_name = payload.get("tool", "")
    inp = _extract_input(payload)
    paths = _extract_paths(tool_name, inp)
    command = _extract_command(tool_name, inp)

    best_spec = -1
    best_effect: str | None = None
    best_rule: dict | None = None

    for rule in rules:
        if not _rule_matches(rule, tool_name, paths, command):
            continue
        spec = _rule_specificity(rule)
        if spec < best_spec:
            continue
        if spec > best_spec:
            best_spec = spec
            best_effect = rule["effect"]
            best_rule = rule
            continue
        # same specificity: deny wins
        if rule["effect"] == DENY:
            best_effect = DENY
            best_rule = rule
    return best_effect, best_rule


def _subagent_allowed_tools(session: str) -> list[str] | None:
    """Return allowed_tools list for a subagent session, or None if caller is
    not a subagent (i.e. no enforcement should apply). Returns [] to mean
    'subagent with no tools permitted' — an empty whitelist blocks everything.
    """
    m = _SUBAGENT_SESSION_RE.match(session or "")
    if not m:
        return None
    sid = m.group(1)
    entry_path = SUBAGENTS_STATE_DIR / f"{sid}.json"
    if not entry_path.is_file():
        return None
    try:
        entry = json.loads(entry_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    tools = entry.get("allowed_tools")
    if not isinstance(tools, list):
        return None
    return [t for t in tools if isinstance(t, str)]


def enforce_subagent_whitelist(payload: dict) -> dict | None:
    """If the hook is for a subagent session, enforce its allowed_tools.

    Returns a deny-rule-like dict when the tool is not in the whitelist, or
    None to defer to the regular rules + interactive approval chain.
    """
    session = payload.get("session", "")
    allowed = _subagent_allowed_tools(session)
    if allowed is None:
        return None
    tool_name = payload.get("tool", "")
    # A few kernel-wide tools are always needed for a subagent to function
    # (status/no-op). Keep the whitelist strictly on user-facing tools.
    if any(fnmatch(tool_name, pat) for pat in allowed):
        return None
    return {
        "tool": tool_name,
        "session": session,
        "reason": "not in subagent allowed_tools",
    }


def save_rules(rules: list[dict]) -> None:
    """Persist rules list to disk."""
    RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    RULES_FILE.write_text(json.dumps({"rules": rules}, indent=2), encoding="utf-8")


def add_rule(rule: dict) -> bool:
    """Add a rule to the persistent store. Returns True if added, False if invalid."""
    if "tool" not in rule or "effect" not in rule:
        return False
    if rule["effect"] not in (ALLOW, DENY):
        return False

    rules = load_rules()

    # Check for duplicate (same tool, path, command) — update effect if found
    for existing in rules:
        if (
            existing.get("tool") == rule.get("tool")
            and existing.get("path") == rule.get("path")
            and existing.get("command") == rule.get("command")
        ):
            if existing.get("effect") != rule.get("effect"):
                existing["effect"] = rule["effect"]
                save_rules(rules)
            return True

    # Prepend new rule (most specific first)
    rules.insert(0, rule)
    save_rules(rules)
    return True


def handle_rule_add(meta: dict) -> None:
    """Handle rule_add command from MSG_MESSAGE meta."""
    rule_data = meta.get("rule_add")
    if not isinstance(rule_data, dict):
        return
    rule = {
        "tool": rule_data.get("tool", "*"),
        "effect": rule_data.get("effect", ALLOW),
    }
    if "path" in rule_data:
        rule["path"] = rule_data["path"]
    if "command" in rule_data:
        rule["command"] = rule_data["command"]
    add_rule(rule)


def run(url: str = TABULA_URL) -> None:
    conn = KernelConnection(url)
    conn.send({
        "type": MSG_CONNECT,
        "name": "hook-approvals",
        "sends": [MSG_HOOK_RESULT],
        "receives": [MSG_HOOK],
        "receives_global": [MSG_MESSAGE],  # receive messages from all sessions
        "hooks": [{"event": HOOK_BEFORE_TOOL_CALL, "priority": 80}],
    })
    conn.recv()  # connected

    try:
        while True:
            msg = conn.recv()
            if msg is None:
                break

            msg_type = msg.get("type")

            # Handle rule_add from MSG_MESSAGE meta (received via receives_global)
            if msg_type == MSG_MESSAGE:
                meta = msg.get("meta")
                if isinstance(meta, dict) and "rule_add" in meta:
                    handle_rule_add(meta)
                continue

            if msg_type != MSG_HOOK:
                continue

            hook_id = msg.get("id", "")
            payload = msg.get("payload", {})

            # Subagent allowed_tools enforcement runs before the rule chain.
            # If the caller is a subagent and the tool isn't on its whitelist,
            # block immediately — no rule can override this.
            sa_block = enforce_subagent_whitelist(payload)
            if sa_block is not None:
                conn.send({
                    "type": MSG_HOOK_RESULT,
                    "id": hook_id,
                    "action": HOOK_BLOCK,
                    "reason": (
                        f"tool '{sa_block['tool']}' not in allowed_tools for "
                        f"subagent session '{sa_block['session']}'"
                    ),
                })
                continue

            rules = load_rules()
            effect, rule = evaluate(rules, payload)

            if effect == DENY:
                tool_name = payload.get("tool", "")
                reason = f"tool '{tool_name}' denied by approvals rule {rule!r}"
                conn.send({
                    "type": MSG_HOOK_RESULT,
                    "id": hook_id,
                    "action": HOOK_BLOCK,
                    "reason": reason,
                })
            elif effect == ALLOW:
                # Stamp the payload as pre-approved so a downstream interactive
                # approval-UI hook can short-circuit and skip prompting.
                inp = _extract_input(payload)
                inp["approved"] = True
                modified = {
                    "tool": payload.get("tool", ""),
                    "id": payload.get("id", ""),
                    "input": inp,
                }
                conn.send({
                    "type": MSG_HOOK_RESULT,
                    "id": hook_id,
                    "action": HOOK_MODIFY,
                    "payload": modified,
                })
            else:
                # No matching rule → pass through to lower-priority hooks.
                conn.send({"type": MSG_HOOK_RESULT, "id": hook_id, "action": HOOK_PASS})
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()


if __name__ == "__main__":
    run()
