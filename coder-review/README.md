# coder-review

Higher-level review / diff UX tools layered on top of `coder-git` and `files`.
Not itself a mutating layer — `diff_preview` and `review_plan` are read-only;
`review_patch` validates a patch via `git apply --check` before handing it off
to `files.apply_patch`.

## Tools

- `diff_preview` — structured working-tree + staged diff with optional path
  filter and context. Returns the same parsed JSON shape as `git_diff`, plus
  a `summary` with per-file stats suitable for TUI rendering.
- `review_plan` — inspect a pending change and produce a checklist
  (files touched, suspicious patterns, size buckets). Meant to drive a
  "ready to commit?" modal.
- `review_patch` — dry-run `git apply --check` against a patch in
  `*** Begin Patch / *** End Patch` form, report what would change.
  Does NOT apply; the driver is expected to route real apply through
  `files.apply_patch`.
