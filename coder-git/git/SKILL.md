---
name: git
description: "Structured git operations for coding agents. Provides status, diff, log, branch, staging, commit, checkout, stash, and blame. No push / no force — those stay with the user."
tools:
  [
    {
      "name": "git_status",
      "description": "Porcelain status of the working tree. Returns lists of staged, unstaged, and untracked files with their status codes.",
      "params": {
        "cwd": { "type": "string", "description": "Directory inside the target git repo. Default: current working directory." }
      },
      "required": []
    },
    {
      "name": "git_diff",
      "description": "Diff of unstaged changes in the working tree. Returns parsed diff with per-file hunks and summary stats.",
      "params": {
        "cwd": { "type": "string" },
        "paths": { "type": "array", "items": { "type": "string" }, "description": "Limit diff to these paths" },
        "context": { "type": "integer", "description": "Context lines per hunk. Default: 3" }
      },
      "required": []
    },
    {
      "name": "git_staged_diff",
      "description": "Diff of staged changes (git diff --cached). Same return shape as git_diff.",
      "params": {
        "cwd": { "type": "string" },
        "paths": { "type": "array", "items": { "type": "string" } },
        "context": { "type": "integer" }
      },
      "required": []
    },
    {
      "name": "git_log",
      "description": "Commit log for the current branch or a given ref. Returns list of commits with hash, author, date, subject.",
      "params": {
        "cwd": { "type": "string" },
        "ref": { "type": "string", "description": "Revision range or ref. Default: HEAD" },
        "limit": { "type": "integer", "description": "Max commits. Default: 50" },
        "paths": { "type": "array", "items": { "type": "string" }, "description": "Restrict history to these paths" }
      },
      "required": []
    },
    {
      "name": "git_show",
      "description": "Show a single commit with its parsed diff. Returns commit metadata plus the same diff shape as git_diff.",
      "params": {
        "cwd": { "type": "string" },
        "ref": { "type": "string", "description": "Commit ref. Default: HEAD" }
      },
      "required": []
    },
    {
      "name": "git_add",
      "description": "Stage one or more paths. Refuses to accept empty paths; use explicit paths instead of '.' to stay deliberate.",
      "params": {
        "cwd": { "type": "string" },
        "paths": { "type": "array", "items": { "type": "string" }, "description": "Paths to stage" }
      },
      "required": ["paths"]
    },
    {
      "name": "git_commit",
      "description": "Create a commit with the given message. Fails if nothing is staged. Never amends unless explicitly requested.",
      "params": {
        "cwd": { "type": "string" },
        "message": { "type": "string", "description": "Commit message. Multi-line ok." },
        "amend": { "type": "boolean", "description": "Amend the last commit instead of creating a new one. Default: false" },
        "allow_empty": { "type": "boolean", "description": "Allow an empty commit. Default: false" }
      },
      "required": ["message"]
    },
    {
      "name": "git_branch",
      "description": "List branches, or create a new one off a starting ref.",
      "params": {
        "cwd": { "type": "string" },
        "action": { "type": "string", "description": "One of: list, create. Default: list" },
        "name": { "type": "string", "description": "Branch name (required for create)" },
        "from": { "type": "string", "description": "Starting ref for create. Default: HEAD" },
        "include_remote": { "type": "boolean", "description": "Include remote branches in list. Default: false" }
      },
      "required": []
    },
    {
      "name": "git_checkout",
      "description": "Switch to an existing branch. Refuses to discard uncommitted changes — stash first.",
      "params": {
        "cwd": { "type": "string" },
        "branch": { "type": "string", "description": "Branch name" },
        "create": { "type": "boolean", "description": "Create the branch if missing (like git switch -c). Default: false" }
      },
      "required": ["branch"]
    },
    {
      "name": "git_stash",
      "description": "Manage git stashes: list, push, pop, apply, drop.",
      "params": {
        "cwd": { "type": "string" },
        "action": { "type": "string", "description": "One of: list, push, pop, apply, drop. Default: list" },
        "message": { "type": "string", "description": "Stash message (push only)" },
        "index": { "type": "integer", "description": "Stash index for pop/apply/drop. Default: 0" },
        "include_untracked": { "type": "boolean", "description": "Include untracked files (push only). Default: false" }
      },
      "required": []
    },
    {
      "name": "git_blame",
      "description": "Per-line blame for a file, with an optional line range.",
      "params": {
        "cwd": { "type": "string" },
        "path": { "type": "string", "description": "File path relative to repo root or absolute" },
        "start": { "type": "integer", "description": "First line (1-based). Default: 1" },
        "end": { "type": "integer", "description": "Last line inclusive. Default: end of file" }
      },
      "required": ["path"]
    }
  ]
---

# git

Structured git operations.

All tools accept an optional `cwd`. When omitted, they run from the current
working directory of the skill subprocess, which is the kernel's cwd. If
`cwd` is outside a git repo every tool returns `{"error": "..."}` instead of
crashing.

## Diff shape

`git_diff`, `git_staged_diff`, and `git_show` return:

```json
{
  "files": [
    {
      "path": "src/main.go",
      "old_path": "src/main.go",
      "status": "modified",
      "added": 7,
      "removed": 2,
      "hunks": [
        {
          "header": "@@ -10,5 +10,10 @@ func main() {",
          "old_start": 10, "old_lines": 5,
          "new_start": 10, "new_lines": 10,
          "lines": [
            {"type": "context", "text": "	ctx := context.Background()"},
            {"type": "added",   "text": "	defer cancel()"},
            {"type": "removed", "text": "	log.Print(\"old\")"}
          ]
        }
      ]
    }
  ],
  "stats": {"files": 1, "added": 7, "removed": 2}
}
```

`status` is one of `added`, `modified`, `deleted`, `renamed`, `copied`.

## Safety rails

- No `git_push`, `git_push_force`, `git_reset --hard`, or history rewriting.
- `git_commit` refuses to amend unless `amend: true` is passed explicitly.
- `git_add` requires an explicit non-empty `paths` array — `["."]` is allowed but you
  have to ask for it.
- `git_checkout` rejects switching when the working tree is dirty; stash or commit
  first.
