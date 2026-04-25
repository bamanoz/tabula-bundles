---
name: review
description: "Inspect pending changes before commit/apply. Use diff_preview for the structured worktree+staged diff, review_plan for a 'ready to commit?' checklist, and review_patch to dry-run a multi-file patch before handing it to files.apply_patch."
tools:
  [
    {
      "name": "diff_preview",
      "description": "Return structured working-tree and staged diffs in a single payload. Output schema matches git_diff (files → hunks → lines) with an extra summary block for TUI rendering.",
      "params": {
        "cwd": { "type": "string", "description": "Repository directory. Default: current working directory" },
        "paths": { "type": "array", "items": { "type": "string" }, "description": "Optional path filter" },
        "context": { "type": "integer", "description": "Diff context lines. Default: 3" },
        "include_staged": { "type": "boolean", "description": "Include staged diff. Default: true" },
        "include_unstaged": { "type": "boolean", "description": "Include working-tree diff. Default: true" }
      },
      "required": []
    },
    {
      "name": "review_plan",
      "description": "Produce a 'ready to commit?' checklist for the pending change: files touched, size buckets, suspicious patterns (TODO/FIXME, debug prints, large binary additions), and a suggested commit message scaffold.",
      "params": {
        "cwd": { "type": "string", "description": "Repository directory. Default: current working directory" },
        "scope": { "type": "string", "description": "One of: working, staged, both. Default: both" }
      },
      "required": []
    },
    {
      "name": "review_patch",
      "description": "Dry-run a multi-file patch in *** Begin Patch / *** End Patch form via `git apply --check`. Returns whether it would apply cleanly and the list of files that would change. Does not apply the patch.",
      "params": {
        "patch_text": { "type": "string", "description": "Patch text to validate" },
        "cwd": { "type": "string", "description": "Repository directory. Default: current working directory" }
      },
      "required": ["patch_text"]
    }
  ]
---

# Review Skill

Read-only review/diff helpers. None of these tools mutate the working tree.

### diff_preview
Combines `git diff` (unstaged) and `git diff --cached` (staged) into one
structured payload. Each entry follows `git_diff`'s schema (`files`, `stats`,
`hunks → lines`) plus a top-level `summary` block:

```json
{
  "summary": {
    "files": 4,
    "added": 120,
    "removed": 17,
    "by_file": [{ "path": "...", "added": 12, "removed": 3, "status": "modified" }]
  },
  "unstaged": { "files": [...], "stats": {...} },
  "staged":   { "files": [...], "stats": {...} }
}
```

### review_plan
Walks the pending change and emits a `checklist` of items the agent (or user)
should confirm before committing. Items include:
- per-file size class (`small`, `medium`, `large`)
- suspicious markers found in added lines (`TODO`, `FIXME`, `XXX`, `print(`,
  `console.log`, `dbg!`, `breakpoint(`)
- new untracked files in the working tree
- suggested conventional-commit prefix based on touched paths

### review_patch
Validates a patch with `git apply --check` so callers can show the diff in a
preview UI before any real apply. The actual apply is the caller's job — point
it at `files.apply_patch` (which uses the same patch envelope).
