#!/usr/bin/env python3
"""review skill — read-only diff/review helpers."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_DIFF_CONTEXT = 3

SUSPICIOUS_PATTERNS = [
    (re.compile(r"\bTODO\b"), "TODO"),
    (re.compile(r"\bFIXME\b"), "FIXME"),
    (re.compile(r"\bXXX\b"), "XXX"),
    (re.compile(r"\bHACK\b"), "HACK"),
    (re.compile(r"\bprint\("), "print("),
    (re.compile(r"\bconsole\.log\("), "console.log("),
    (re.compile(r"\bdbg!\("), "dbg!("),
    (re.compile(r"\bbreakpoint\("), "breakpoint("),
    (re.compile(r"\bdebugger\b"), "debugger"),
]

SIZE_BUCKETS = [(20, "small"), (200, "medium")]  # else "large"


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


def _git(args: list[str], cwd: str, *, check: bool = True, stdin: str | None = None) -> subprocess.CompletedProcess:
    r = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, input=stdin,
    )
    if check and r.returncode != 0:
        raise ToolError(
            f"git {' '.join(args)} failed (exit {r.returncode}): {r.stderr.strip() or r.stdout.strip()}"
        )
    return r


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


# --- diff parsing (mirrors coder-git/git/run.py) ---------------------------

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

    def _flush() -> None:
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
            _flush()
            old_path, new_path = m.group(1), m.group(2)
            current = {
                "path": new_path, "old_path": old_path, "status": "modified",
                "added": 0, "removed": 0, "hunks": [],
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

    _flush()
    return {
        "files": files,
        "stats": {"files": len(files), "added": total_added, "removed": total_removed},
    }


# --- tools -----------------------------------------------------------------

def _diff_args(staged: bool, ctx: int, paths: list[str] | None) -> list[str]:
    args = ["diff", "--no-color"]
    if staged:
        args.append("--cached")
    args.append(f"--unified={ctx}")
    if paths:
        args.append("--")
        args += paths
    return args


def _untracked(cwd: str) -> list[str]:
    r = _git(["ls-files", "--others", "--exclude-standard"], cwd, check=False)
    if r.returncode != 0:
        return []
    return [line for line in r.stdout.splitlines() if line.strip()]


def diff_preview(params: dict) -> str:
    try:
        cwd = _cwd_of(params)
        _ensure_repo(cwd)
        ctx = _coerce_int(params, "context", DEFAULT_DIFF_CONTEXT, minimum=0)
        include_staged = _coerce_bool(params.get("include_staged"), True)
        include_unstaged = _coerce_bool(params.get("include_unstaged"), True)
        paths = params.get("paths")
        if paths is not None:
            if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
                raise ToolError("paths must be an array of strings")
        else:
            paths = []

        result: dict = {}
        merged_by_file: dict[str, dict] = {}
        total_added = 0
        total_removed = 0

        if include_unstaged:
            raw = _git(_diff_args(False, ctx, paths), cwd).stdout
            unstaged = _parse_diff(raw)
            result["unstaged"] = unstaged
            for f in unstaged["files"]:
                key = f["path"]
                entry = merged_by_file.setdefault(key, {"path": key, "added": 0, "removed": 0, "status": f["status"]})
                entry["added"] += f["added"]
                entry["removed"] += f["removed"]
                total_added += f["added"]
                total_removed += f["removed"]

        if include_staged:
            raw = _git(_diff_args(True, ctx, paths), cwd).stdout
            staged = _parse_diff(raw)
            result["staged"] = staged
            for f in staged["files"]:
                key = f["path"]
                entry = merged_by_file.setdefault(key, {"path": key, "added": 0, "removed": 0, "status": f["status"]})
                entry["added"] += f["added"]
                entry["removed"] += f["removed"]
                total_added += f["added"]
                total_removed += f["removed"]

        result["summary"] = {
            "files": len(merged_by_file),
            "added": total_added,
            "removed": total_removed,
            "by_file": list(merged_by_file.values()),
        }
        return json.dumps(result, ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))


def _bucket(total: int) -> str:
    for limit, name in SIZE_BUCKETS:
        if total <= limit:
            return name
    return "large"


def _scan_added_lines(parsed: dict) -> list[dict]:
    findings: list[dict] = []
    for f in parsed.get("files", []):
        for h in f.get("hunks", []):
            for ln in h.get("lines", []):
                if ln.get("type") != "added":
                    continue
                text = ln.get("text", "")
                for pat, label in SUSPICIOUS_PATTERNS:
                    if pat.search(text):
                        findings.append({"path": f["path"], "marker": label, "text": text.rstrip()})
                        break
    return findings


def _commit_prefix(paths: list[str]) -> str:
    if not paths:
        return "chore"
    if any(p.startswith("docs/") or p.endswith(".md") for p in paths):
        return "docs"
    if any("test" in p.lower() for p in paths):
        return "test"
    if any(p.endswith((".yml", ".yaml", ".toml", ".json")) and ("ci" in p or ".github" in p) for p in paths):
        return "ci"
    return "feat"


def review_plan(params: dict) -> str:
    try:
        cwd = _cwd_of(params)
        _ensure_repo(cwd)
        scope = params.get("scope") or "both"
        if scope not in {"working", "staged", "both"}:
            raise ToolError("scope must be one of: working, staged, both")

        include_unstaged = scope in {"working", "both"}
        include_staged = scope in {"staged", "both"}

        diffs: list[dict] = []
        if include_unstaged:
            diffs.append(_parse_diff(_git(_diff_args(False, DEFAULT_DIFF_CONTEXT, None), cwd).stdout))
        if include_staged:
            diffs.append(_parse_diff(_git(_diff_args(True, DEFAULT_DIFF_CONTEXT, None), cwd).stdout))

        per_file: dict[str, dict] = {}
        for d in diffs:
            for f in d["files"]:
                key = f["path"]
                e = per_file.setdefault(key, {"path": key, "status": f["status"], "added": 0, "removed": 0})
                e["added"] += f["added"]
                e["removed"] += f["removed"]

        for e in per_file.values():
            e["bucket"] = _bucket(e["added"] + e["removed"])

        suspicious: list[dict] = []
        for d in diffs:
            suspicious.extend(_scan_added_lines(d))

        untracked = _untracked(cwd)

        checklist: list[dict] = []
        for e in per_file.values():
            if e["bucket"] == "large":
                checklist.append({
                    "type": "large_change",
                    "path": e["path"],
                    "message": f"{e['path']} touches {e['added'] + e['removed']} lines — consider splitting",
                })
        for s in suspicious:
            checklist.append({
                "type": "suspicious_marker",
                "path": s["path"],
                "marker": s["marker"],
                "message": f"{s['marker']} found in added line of {s['path']}",
            })
        if untracked:
            checklist.append({
                "type": "untracked",
                "paths": untracked,
                "message": f"{len(untracked)} untracked file(s) — git_add or .gitignore them",
            })

        prefix = _commit_prefix(list(per_file.keys()))
        scaffold = f"{prefix}: <subject>\n\n<why>\n"

        return json.dumps({
            "scope": scope,
            "files": list(per_file.values()),
            "untracked": untracked,
            "checklist": checklist,
            "suggested_commit": scaffold,
        }, ensure_ascii=False)
    except ToolError as exc:
        return _err(str(exc))


def review_patch(params: dict) -> str:
    try:
        cwd = _cwd_of(params)
        _ensure_repo(cwd)
        patch = params.get("patch_text")
        if not isinstance(patch, str) or not patch.strip():
            raise ToolError("patch_text must be a non-empty string")

        # git apply --check expects unified diff. The *** Begin Patch envelope
        # used by files.apply_patch is not a unified diff, so we sniff and
        # report which mode we're in. We only validate unified diffs here;
        # the envelope form gets a static parse that lists targeted paths.
        is_envelope = patch.lstrip().startswith("*** Begin Patch")
        if is_envelope:
            paths: list[str] = []
            ops: list[dict] = []
            for line in patch.splitlines():
                stripped = line.strip()
                if stripped.startswith("*** "):
                    stripped = stripped[4:]
                for op in ("Add File:", "Update File:", "Delete File:", "Move File:"):
                    if stripped.startswith(op):
                        rest = stripped[len(op):].strip()
                        paths.append(rest.split(" -> ")[0])
                        ops.append({"op": op[:-1].lower().replace(" ", "_"), "target": rest})
                        break
            return json.dumps({
                "format": "envelope",
                "would_apply": True,
                "note": "envelope-form patch — apply via files.apply_patch (no git apply check available)",
                "operations": ops,
                "paths_touched": paths,
            }, ensure_ascii=False)

        # Unified diff path: feed to git apply --check via a temp file so git
        # can resolve relative paths from cwd.
        with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as tf:
            tf.write(patch)
            tf_path = tf.name
        try:
            r = subprocess.run(
                ["git", "apply", "--check", tf_path],
                cwd=cwd, capture_output=True, text=True,
            )
            ok = r.returncode == 0
            stat = subprocess.run(
                ["git", "apply", "--stat", tf_path],
                cwd=cwd, capture_output=True, text=True,
            )
            return json.dumps({
                "format": "unified",
                "would_apply": ok,
                "stderr": r.stderr.strip(),
                "stat": stat.stdout.strip(),
            }, ensure_ascii=False)
        finally:
            try:
                os.unlink(tf_path)
            except OSError:
                pass
    except ToolError as exc:
        return _err(str(exc))


# --- dispatch --------------------------------------------------------------

TOOLS = {
    "diff_preview": diff_preview,
    "review_plan": review_plan,
    "review_patch": review_patch,
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
