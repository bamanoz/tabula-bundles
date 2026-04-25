#!/usr/bin/env python3
"""git skill — structured git operations."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


DEFAULT_LOG_LIMIT = 50
DEFAULT_DIFF_CONTEXT = 3


class ToolError(Exception):
    pass


# --- helpers ---------------------------------------------------------------

def _err(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


def _cwd_of(params: dict) -> str:
    raw = params.get("cwd")
    if isinstance(raw, str) and raw.strip():
        return str(Path(os.path.expanduser(raw)).resolve())
    return os.getcwd()


def _ensure_repo(cwd: str) -> None:
    r = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd, capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise ToolError(f"not a git repository (cwd={cwd})")


def _git(args: list[str], cwd: str, *, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
    )
    if check and r.returncode != 0:
        raise ToolError(
            f"git {' '.join(args)} failed (exit {r.returncode}): {r.stderr.strip() or r.stdout.strip()}"
        )
    return r


def _require_list_of_str(params: dict, key: str, *, allow_empty: bool = False) -> list[str]:
    v = params.get(key)
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ToolError(f"{key} must be an array of strings")
    if not allow_empty and not v:
        raise ToolError(f"{key} must be non-empty")
    return list(v)


def _require_str(params: dict, key: str) -> str:
    v = params.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ToolError(f"{key} must be a non-empty string")
    return v


def _coerce_int(params: dict, key: str, default: int, minimum: int = 0) -> int:
    v = params.get(key, default)
    try:
        n = int(v)
    except (TypeError, ValueError) as exc:
        raise ToolError(f"{key} must be an integer") from exc
    if n < minimum:
        raise ToolError(f"{key} must be >= {minimum}")
    return n


def _coerce_bool(v, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "on"}
    return bool(v)


# --- diff parsing ----------------------------------------------------------

_DIFF_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DIFF_FILE_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")


def _parse_diff(raw: str) -> dict:
    files: list[dict] = []
    current: dict | None = None
    hunk: dict | None = None
    total_added = 0
    total_removed = 0

    lines = raw.splitlines()
    i = 0
    n = len(lines)

    def _flush_file() -> None:
        nonlocal current, hunk
        if hunk is not None and current is not None:
            current["hunks"].append(hunk)
            hunk = None
        if current is not None:
            files.append(current)
            current = None

    while i < n:
        line = lines[i]
        m = _DIFF_FILE_RE.match(line)
        if m:
            _flush_file()
            old_path, new_path = m.group(1), m.group(2)
            current = {
                "path": new_path,
                "old_path": old_path,
                "status": "modified",
                "added": 0,
                "removed": 0,
                "hunks": [],
            }
            hunk = None
            i += 1
            continue

        if current is None:
            i += 1
            continue

        if line.startswith("new file mode"):
            current["status"] = "added"
            current["old_path"] = None
        elif line.startswith("deleted file mode"):
            current["status"] = "deleted"
            current["path"] = current.get("old_path") or current["path"]
        elif line.startswith("rename from "):
            current["status"] = "renamed"
            current["old_path"] = line[len("rename from "):]
        elif line.startswith("rename to "):
            current["path"] = line[len("rename to "):]
        elif line.startswith("copy from "):
            current["status"] = "copied"
            current["old_path"] = line[len("copy from "):]
        elif line.startswith("copy to "):
            current["path"] = line[len("copy to "):]

        m = _DIFF_HUNK_RE.match(line)
        if m:
            if hunk is not None:
                current["hunks"].append(hunk)
            hunk = {
                "header": line,
                "old_start": int(m.group(1)),
                "old_lines": int(m.group(2) or "1"),
                "new_start": int(m.group(3)),
                "new_lines": int(m.group(4) or "1"),
                "lines": [],
            }
            i += 1
            continue

        if hunk is not None and line and line[0] in (" ", "+", "-"):
            if line.startswith("+++") or line.startswith("---"):
                i += 1
                continue
            if line[0] == "+":
                hunk["lines"].append({"type": "added", "text": line[1:]})
                current["added"] += 1
                total_added += 1
            elif line[0] == "-":
                hunk["lines"].append({"type": "removed", "text": line[1:]})
                current["removed"] += 1
                total_removed += 1
            else:
                hunk["lines"].append({"type": "context", "text": line[1:]})
        i += 1

    _flush_file()
    return {
        "files": files,
        "stats": {"files": len(files), "added": total_added, "removed": total_removed},
    }


# --- tool implementations --------------------------------------------------

_STATUS_CODES = {
    "M": "modified", "A": "added", "D": "deleted", "R": "renamed",
    "C": "copied", "U": "unmerged", "?": "untracked", "!": "ignored", " ": "",
}


def _parse_porcelain(raw: str) -> dict:
    staged: list[dict] = []
    unstaged: list[dict] = []
    untracked: list[str] = []
    for line in raw.splitlines():
        if not line:
            continue
        xy = line[:2]
        rest = line[3:]
        x, y = xy[0], xy[1]
        if x == "?" and y == "?":
            untracked.append(rest)
            continue
        # rename syntax: "orig -> new"
        old_path = None
        path = rest
        if " -> " in rest:
            old_path, path = rest.split(" -> ", 1)
        if x != " " and x != "?":
            staged.append({"status": _STATUS_CODES.get(x, x), "path": path, "old_path": old_path})
        if y != " " and y != "?":
            unstaged.append({"status": _STATUS_CODES.get(y, y), "path": path, "old_path": old_path})
    return {"staged": staged, "unstaged": unstaged, "untracked": untracked}


def git_status(params: dict) -> str:
    try:
        cwd = _cwd_of(params)
        _ensure_repo(cwd)
        out = _git(["status", "--porcelain=v1"], cwd).stdout
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd, check=False).stdout.strip()
        result = _parse_porcelain(out)
        result["branch"] = branch or None
        return json.dumps(result, ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))


def _diff_args(params: dict, *, staged: bool) -> list[str]:
    args = ["diff", "--no-color"]
    if staged:
        args.append("--cached")
    ctx = _coerce_int(params, "context", DEFAULT_DIFF_CONTEXT, minimum=0)
    args += [f"--unified={ctx}"]
    paths = params.get("paths")
    if isinstance(paths, list) and paths:
        if not all(isinstance(p, str) for p in paths):
            raise ToolError("paths must be an array of strings")
        args.append("--")
        args += paths
    return args


def git_diff(params: dict) -> str:
    try:
        cwd = _cwd_of(params)
        _ensure_repo(cwd)
        out = _git(_diff_args(params, staged=False), cwd).stdout
        return json.dumps(_parse_diff(out), ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))


def git_staged_diff(params: dict) -> str:
    try:
        cwd = _cwd_of(params)
        _ensure_repo(cwd)
        out = _git(_diff_args(params, staged=True), cwd).stdout
        return json.dumps(_parse_diff(out), ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))


_LOG_SEP = "\x1eENDCOMMIT\x1e"
_LOG_FIELD = "\x1f"
_LOG_FORMAT = (
    f"%H{_LOG_FIELD}%h{_LOG_FIELD}%an{_LOG_FIELD}%ae{_LOG_FIELD}%ad"
    f"{_LOG_FIELD}%s{_LOG_FIELD}%P{_LOG_SEP}"
)


def git_log(params: dict) -> str:
    try:
        cwd = _cwd_of(params)
        _ensure_repo(cwd)
        ref = params.get("ref") or "HEAD"
        limit = _coerce_int(params, "limit", DEFAULT_LOG_LIMIT, minimum=1)
        args = ["log", f"-n{limit}", "--date=iso-strict", f"--pretty=format:{_LOG_FORMAT}", ref]
        paths = params.get("paths")
        if isinstance(paths, list) and paths:
            if not all(isinstance(p, str) for p in paths):
                raise ToolError("paths must be an array of strings")
            args.append("--")
            args += paths
        out = _git(args, cwd).stdout
        commits = []
        for entry in out.split(_LOG_SEP):
            entry = entry.strip("\n")
            if not entry:
                continue
            parts = entry.split(_LOG_FIELD)
            if len(parts) < 7:
                continue
            h, short, author, email, date, subject, parents = parts[:7]
            commits.append({
                "hash": h,
                "short": short,
                "author": author,
                "email": email,
                "date": date,
                "subject": subject,
                "parents": parents.split() if parents else [],
            })
        return json.dumps({"commits": commits}, ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))


def git_show(params: dict) -> str:
    try:
        cwd = _cwd_of(params)
        _ensure_repo(cwd)
        ref = params.get("ref") or "HEAD"
        if not isinstance(ref, str):
            raise ToolError("ref must be a string")
        meta_raw = _git(
            ["show", "--no-color", "--no-patch", f"--pretty=format:{_LOG_FORMAT}", ref],
            cwd,
        ).stdout
        parts = meta_raw.split(_LOG_FIELD)
        meta: dict = {}
        if len(parts) >= 7:
            h, short, author, email, date, subject, parents = parts[:7]
            parents = parents.split(_LOG_SEP)[0]  # trim trailing separator
            meta = {
                "hash": h, "short": short, "author": author, "email": email,
                "date": date, "subject": subject,
                "parents": parents.split() if parents else [],
            }
        diff_raw = _git(
            ["show", "--no-color", f"--unified={DEFAULT_DIFF_CONTEXT}", "--format=", ref],
            cwd,
        ).stdout
        return json.dumps({"commit": meta, **_parse_diff(diff_raw)}, ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))


def git_add(params: dict) -> str:
    try:
        cwd = _cwd_of(params)
        _ensure_repo(cwd)
        paths = _require_list_of_str(params, "paths")
        _git(["add", "--", *paths], cwd)
        # Return updated status summary for convenience.
        out = _git(["status", "--porcelain=v1"], cwd).stdout
        return json.dumps({"added": paths, "status": _parse_porcelain(out)}, ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))


def git_commit(params: dict) -> str:
    try:
        cwd = _cwd_of(params)
        _ensure_repo(cwd)
        message = _require_str(params, "message")
        amend = _coerce_bool(params.get("amend"), False)
        allow_empty = _coerce_bool(params.get("allow_empty"), False)

        args = ["commit", "-m", message]
        if amend:
            args.append("--amend")
        if allow_empty:
            args.append("--allow-empty")

        r = _git(args, cwd, check=False)
        if r.returncode != 0:
            err = r.stderr.strip() or r.stdout.strip()
            return _err(f"git commit failed: {err}")

        head = _git(
            ["log", "-1", f"--pretty=format:{_LOG_FORMAT}"], cwd,
        ).stdout
        parts = head.split(_LOG_FIELD)
        commit_info: dict = {}
        if len(parts) >= 7:
            h, short, author, email, date, subject, parents = parts[:7]
            parents = parents.split(_LOG_SEP)[0]
            commit_info = {
                "hash": h, "short": short, "author": author, "email": email,
                "date": date, "subject": subject,
                "parents": parents.split() if parents else [],
            }
        return json.dumps({"committed": True, "commit": commit_info, "amended": amend}, ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))


def git_branch(params: dict) -> str:
    try:
        cwd = _cwd_of(params)
        _ensure_repo(cwd)
        action = params.get("action") or "list"
        if action == "list":
            include_remote = _coerce_bool(params.get("include_remote"), False)
            args = ["branch", "--format=%(refname:short)\t%(HEAD)\t%(objectname:short)"]
            if include_remote:
                args.append("-a")
            out = _git(args, cwd).stdout
            branches = []
            for line in out.splitlines():
                if not line.strip():
                    continue
                cols = line.split("\t")
                if len(cols) < 3:
                    continue
                name, head_flag, sha = cols
                branches.append({
                    "name": name,
                    "current": head_flag.strip() == "*",
                    "sha": sha,
                })
            return json.dumps({"branches": branches}, ensure_ascii=False)

        if action == "create":
            name = _require_str(params, "name")
            start = params.get("from") or "HEAD"
            if not isinstance(start, str):
                raise ToolError("from must be a string")
            _git(["branch", name, start], cwd)
            return json.dumps({"created": name, "from": start}, ensure_ascii=False)

        raise ToolError(f"unknown action: {action}")
    except ToolError as exc:
        return _err(str(exc))


def _is_dirty(cwd: str) -> bool:
    r = _git(["status", "--porcelain=v1"], cwd)
    return bool(r.stdout.strip())


def git_checkout(params: dict) -> str:
    try:
        cwd = _cwd_of(params)
        _ensure_repo(cwd)
        branch = _require_str(params, "branch")
        create = _coerce_bool(params.get("create"), False)
        if _is_dirty(cwd):
            return _err(
                "working tree has uncommitted changes — commit or stash before checkout"
            )
        args = ["switch"]
        if create:
            args.append("-c")
        args.append(branch)
        _git(args, cwd)
        return json.dumps({"switched_to": branch, "created": create}, ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))


def git_stash(params: dict) -> str:
    try:
        cwd = _cwd_of(params)
        _ensure_repo(cwd)
        action = params.get("action") or "list"

        if action == "list":
            out = _git(["stash", "list"], cwd).stdout
            entries = []
            for i, line in enumerate(out.splitlines()):
                if not line:
                    continue
                entries.append({"index": i, "line": line})
            return json.dumps({"stashes": entries}, ensure_ascii=False)

        if action == "push":
            args = ["stash", "push"]
            if _coerce_bool(params.get("include_untracked"), False):
                args.append("-u")
            message = params.get("message")
            if isinstance(message, str) and message.strip():
                args += ["-m", message]
            out = _git(args, cwd).stdout
            return json.dumps({"pushed": True, "output": out.strip()}, ensure_ascii=False)

        if action in ("pop", "apply", "drop"):
            idx = _coerce_int(params, "index", 0, minimum=0)
            ref = f"stash@{{{idx}}}"
            _git(["stash", action, ref], cwd)
            return json.dumps({"action": action, "ref": ref}, ensure_ascii=False)

        raise ToolError(f"unknown action: {action}")
    except ToolError as exc:
        return _err(str(exc))


def git_blame(params: dict) -> str:
    try:
        cwd = _cwd_of(params)
        _ensure_repo(cwd)
        path = _require_str(params, "path")
        start = _coerce_int(params, "start", 1, minimum=1)
        end = params.get("end")
        args = ["blame", "--porcelain"]
        if end is not None:
            end_n = int(end)
            if end_n < start:
                raise ToolError("end must be >= start")
            args += ["-L", f"{start},{end_n}"]
        else:
            args += ["-L", f"{start},"]
        args += ["--", path]
        out = _git(args, cwd).stdout

        entries: list[dict] = []
        meta_cache: dict[str, dict] = {}
        current: dict | None = None
        for line in out.splitlines():
            if not line:
                continue
            if line.startswith("\t"):
                if current is not None:
                    current["text"] = line[1:]
                    entries.append(current)
                    current = None
                continue
            parts = line.split()
            if len(parts) >= 3 and len(parts[0]) == 40 and parts[1].isdigit() and parts[2].isdigit():
                sha = parts[0]
                current = {
                    "sha": sha,
                    "orig_line": int(parts[1]),
                    "final_line": int(parts[2]),
                    **meta_cache.get(sha, {}),
                }
                continue
            if current is None:
                continue
            key, _, value = line.partition(" ")
            normalized = key.replace("-", "_")
            if normalized in {"author", "author_mail", "author_time", "summary"}:
                current[normalized] = value
                meta_cache.setdefault(current["sha"], {})[normalized] = value
        return json.dumps({"path": path, "entries": entries}, ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))


# --- dispatch --------------------------------------------------------------

TOOLS = {
    "git_status": git_status,
    "git_diff": git_diff,
    "git_staged_diff": git_staged_diff,
    "git_log": git_log,
    "git_show": git_show,
    "git_add": git_add,
    "git_commit": git_commit,
    "git_branch": git_branch,
    "git_checkout": git_checkout,
    "git_stash": git_stash,
    "git_blame": git_blame,
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
