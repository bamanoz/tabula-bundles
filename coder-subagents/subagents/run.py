#!/usr/bin/env python3
"""subagents skill — typed subagent spawn/steer/list/wait/kill orchestration."""

from __future__ import annotations

import errno
import json
import os
import re
import signal
import subprocess
import sys
import time
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = os.environ.get("TABULA_HOME", os.path.expanduser("~/.tabula"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from skills._pylib.paths import (
    ensure_parent,
    skill_logs_dir,
    skill_state_dir,
    tabula_home,
)

SCHEMA_VERSION = 1
DEFAULT_WAIT_TIMEOUT = 120
KILL_GRACE_SECONDS = 3
ALLOWED_MODES = {"sync", "async"}
ALLOWED_STATUSES = {"running", "completed", "failed", "killed"}
_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_TYPE_RE = re.compile(r"^[A-Za-z0-9_-]+$")

SUPPORTED_PROVIDERS = {"openai", "anthropic"}

TYPES_DIR = tabula_home() / "skills" / "_subagent_types"
LEGACY_TYPES_DIR = Path(__file__).resolve().parent.parent / "types"


class ToolError(Exception):
    pass


def _err(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _session_id() -> str:
    raw = os.environ.get("TABULA_SESSION", "").strip()
    return raw if raw and _ID_RE.match(raw) else "_default"


def _registry_dir() -> Path:
    return skill_state_dir("subagents")


def _registry_file(sid: str) -> Path:
    return _registry_dir() / f"{sid}.json"


def _result_file(sid: str) -> Path:
    return _registry_dir() / f"{sid}.result.txt"


def _log_file(sid: str) -> Path:
    return skill_logs_dir("subagents") / f"{sid}.log"


def _atomic_write_json(path: Path, data: dict) -> None:
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read_registry(sid: str) -> dict | None:
    path = _registry_file(sid)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _list_registry() -> list[dict]:
    out: list[dict] = []
    d = _registry_dir()
    if not d.is_dir():
        return out
    for entry in sorted(d.iterdir()):
        if entry.suffix != ".json" or entry.name.endswith(".tmp"):
            continue
        try:
            out.append(json.loads(entry.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        return False
    return True


def _update_entry(sid: str, **fields) -> dict | None:
    entry = _read_registry(sid)
    if entry is None:
        return None
    entry.update(fields)
    entry["updated_at"] = _now()
    _atomic_write_json(_registry_file(sid), entry)
    return entry


def _reconcile(entry: dict) -> dict:
    """If the registry says running but the pid is dead, flip to completed/failed."""
    if entry.get("status") != "running":
        return entry
    pid = int(entry.get("pid") or 0)
    if _pid_alive(pid):
        return entry
    sid = entry["id"]
    result_path = _result_file(sid)
    final_status = "completed" if result_path.is_file() else "failed"
    updated = _update_entry(
        sid,
        status=final_status,
        ended_at=_now(),
        result=(result_path.read_text(encoding="utf-8") if result_path.is_file() else None),
    )
    return updated or entry


def _load_preset(type_name: str) -> dict:
    if not _TYPE_RE.match(type_name or ""):
        raise ToolError(f"invalid type: {type_name!r}")
    path = TYPES_DIR / f"{type_name}.toml"
    if not path.is_file():
        legacy = LEGACY_TYPES_DIR / f"{type_name}.toml"
        if legacy.is_file():
            path = legacy
    if not path.is_file():
        raise ToolError(f"unknown type: {type_name!r} (no {path.name} in types/)")
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except Exception as exc:
        raise ToolError(f"failed to parse preset {path}: {exc}") from exc


def _resolve_runner(provider: str) -> Path:
    if provider not in SUPPORTED_PROVIDERS:
        raise ToolError(f"unsupported provider: {provider!r}")
    path = tabula_home() / "skills" / "subagent" / "run.py"
    if not path.is_file():
        raise ToolError(f"subagent runner not installed: {path}")
    return path


def _new_id() -> str:
    return "sa-" + uuid.uuid4().hex[:10]


def _build_task(preset: dict, task: str) -> str:
    suffix = preset.get("system_suffix") or ""
    if suffix:
        return f"{suffix.strip()}\n\n---\n\n{task.strip()}"
    return task.strip()


def _deliver_message(sid: str, text: str) -> None:
    """Send a MSG_MESSAGE into the subagent's kernel session."""
    from skills._pylib.kernel_client import KernelConnection
    from skills._pylib.protocol import (
        MSG_CONNECT,
        MSG_JOIN,
        MSG_MESSAGE,
    )

    url = os.environ.get("TABULA_URL", "ws://localhost:8089/ws")
    spawn_token = os.environ.get("TABULA_SPAWN_TOKEN", "")
    session_name = f"subagent-{sid}"

    conn = KernelConnection(url)
    try:
        msg = {
            "type": MSG_CONNECT,
            "name": f"subagent-sender-{sid}-{uuid.uuid4().hex[:6]}",
            "sends": [MSG_MESSAGE],
            "receives": [],
        }
        if spawn_token:
            msg["token"] = spawn_token
        conn.send(msg)
        conn.recv(timeout=5)
        conn.send({"type": MSG_JOIN, "session": session_name})
        conn.recv(timeout=5)
        conn.send({"type": MSG_MESSAGE, "text": text})
    finally:
        conn.close()


# ── tools ──────────────────────────────────────────────────────────────────


def subagent_spawn(params: dict) -> str:
    try:
        type_name = params.get("type")
        task = params.get("task")
        if not isinstance(type_name, str) or not type_name.strip():
            raise ToolError("type must be a non-empty string")
        if not isinstance(task, str) or not task.strip():
            raise ToolError("task must be a non-empty string")

        preset = _load_preset(type_name.strip())
        provider = preset.get("provider", "openai")
        runner = _resolve_runner(provider)

        sid = params.get("id")
        if sid is not None:
            if not isinstance(sid, str) or not _ID_RE.match(sid):
                raise ToolError("id must match [A-Za-z0-9._-]+")
            if _registry_file(sid).is_file():
                raise ToolError(f"subagent {sid!r} already exists")
        else:
            sid = _new_id()

        mode = params.get("mode") or "async"
        if mode not in ALLOWED_MODES:
            raise ToolError(f"mode must be one of {sorted(ALLOWED_MODES)}")

        max_turns = int(params.get("max_turns") or preset.get("max_turns") or 20)
        timeout = int(params.get("timeout") or preset.get("timeout") or 0)
        model = params.get("model") or preset.get("model")
        allowed_tools = params.get("allowed_tools") or preset.get("allowed_tools") or []
        cwd = params.get("cwd")
        parent_session = _session_id()
        enriched_task = _build_task(preset, task)

        cmd: list[str] = [
            sys.executable,
            str(runner),
            "--provider", provider,
            "--id", sid,
            "--parent-session", parent_session,
            "--task", enriched_task,
            "--max-turns", str(max_turns),
            "--timeout", str(timeout),
        ]
        if model:
            cmd.extend(["--model", str(model)])

        log_path = ensure_parent(_log_file(sid))
        log_fh = open(log_path, "ab", buffering=0)

        popen_kwargs: dict = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_fh,
            "stderr": log_fh,
            "start_new_session": True,
        }
        if cwd:
            cwd_path = Path(cwd).expanduser().resolve()
            if not cwd_path.is_dir():
                raise ToolError(f"cwd does not exist: {cwd_path}")
            popen_kwargs["cwd"] = str(cwd_path)

        proc = subprocess.Popen(cmd, **popen_kwargs)

        entry = {
            "version": SCHEMA_VERSION,
            "id": sid,
            "parent_session": parent_session,
            "session": f"subagent-{sid}",
            "type": type_name,
            "provider": provider,
            "model": model,
            "pid": proc.pid,
            "status": "running",
            "cmd": cmd,
            "allowed_tools": list(allowed_tools) if isinstance(allowed_tools, list) else [],
            "cwd": popen_kwargs.get("cwd") or os.getcwd(),
            "task": task,
            "max_turns": max_turns,
            "timeout": timeout,
            "mode": mode,
            "result_file": str(_result_file(sid)),
            "log_file": str(log_path),
            "created_at": _now(),
            "updated_at": _now(),
            "ended_at": None,
            "result": None,
        }
        _atomic_write_json(_registry_file(sid), entry)

        if mode == "sync":
            timeout_val = int(params.get("timeout") or DEFAULT_WAIT_TIMEOUT)
            return subagent_wait({"id": sid, "timeout": timeout_val})

        return json.dumps(entry, ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))
    except Exception as exc:  # pragma: no cover — defensive
        return _err(f"spawn failed: {exc}")


def subagent_send(params: dict) -> str:
    try:
        sid = params.get("id")
        text = params.get("message")
        if not isinstance(sid, str) or not _ID_RE.match(sid or ""):
            raise ToolError("id must be a valid subagent id")
        if not isinstance(text, str) or not text.strip():
            raise ToolError("message must be a non-empty string")
        entry = _read_registry(sid)
        if entry is None:
            raise ToolError(f"unknown subagent: {sid}")
        entry = _reconcile(entry)
        if entry.get("status") != "running":
            raise ToolError(f"subagent {sid} is not running (status={entry.get('status')})")
        _deliver_message(sid, text.strip())
        return json.dumps({"id": sid, "delivered": True, "at": _now()}, ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))
    except Exception as exc:
        return _err(f"send failed: {exc}")


def subagent_steer(params: dict) -> str:
    instruction = params.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        return _err("instruction must be a non-empty string")
    prefixed = f"[steering] {instruction.strip()}"
    return subagent_send({"id": params.get("id"), "message": prefixed})


def subagent_wait(params: dict) -> str:
    try:
        sid = params.get("id")
        if not isinstance(sid, str) or not _ID_RE.match(sid or ""):
            raise ToolError("id must be a valid subagent id")
        timeout = params.get("timeout")
        if timeout is None:
            timeout = DEFAULT_WAIT_TIMEOUT
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            raise ToolError("timeout must be an integer")

        entry = _read_registry(sid)
        if entry is None:
            raise ToolError(f"unknown subagent: {sid}")

        deadline = time.monotonic() + max(0, timeout)
        while True:
            entry = _reconcile(entry)
            if entry.get("status") != "running":
                return json.dumps(entry, ensure_ascii=False)
            if time.monotonic() >= deadline:
                return json.dumps(
                    {"timeout": True, "id": sid, "status": entry.get("status"), "entry": entry},
                    ensure_ascii=False,
                )
            time.sleep(0.5)
            entry = _read_registry(sid) or entry
    except ToolError as exc:
        return _err(str(exc))


def subagent_list(params: dict) -> str:
    try:
        parent_session = params.get("parent_session")
        if parent_session is None:
            parent_session = _session_id()
        status_filter = params.get("status")
        if status_filter is not None and status_filter not in ALLOWED_STATUSES:
            raise ToolError(f"status must be one of {sorted(ALLOWED_STATUSES)}")

        items: list[dict] = []
        for entry in _list_registry():
            entry = _reconcile(entry)
            if parent_session and entry.get("parent_session") != parent_session:
                continue
            if status_filter and entry.get("status") != status_filter:
                continue
            items.append(entry)
        return json.dumps({"items": items}, ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))


def subagent_kill(params: dict) -> str:
    try:
        sid = params.get("id")
        if not isinstance(sid, str) or not _ID_RE.match(sid or ""):
            raise ToolError("id must be a valid subagent id")
        entry = _read_registry(sid)
        if entry is None:
            raise ToolError(f"unknown subagent: {sid}")
        entry = _reconcile(entry)
        if entry.get("status") != "running":
            return json.dumps(entry, ensure_ascii=False)

        pid = int(entry.get("pid") or 0)
        if pid <= 0 or not _pid_alive(pid):
            updated = _update_entry(sid, status="failed", ended_at=_now())
            return json.dumps(updated or entry, ensure_ascii=False)

        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

        deadline = time.monotonic() + KILL_GRACE_SECONDS
        while _pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        if _pid_alive(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

        updated = _update_entry(sid, status="killed", ended_at=_now())
        return json.dumps(updated or entry, ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))


TOOLS = {
    "subagent_spawn": subagent_spawn,
    "subagent_send": subagent_send,
    "subagent_steer": subagent_steer,
    "subagent_wait": subagent_wait,
    "subagent_list": subagent_list,
    "subagent_kill": subagent_kill,
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
