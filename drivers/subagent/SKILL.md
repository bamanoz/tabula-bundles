---
name: subagent
description: "Unified Tabula LLM subagent runner. Usage: `python3 skills/subagent/run.py --provider openai|anthropic --id <id> --parent-session <session> --task <task>`."
---

# subagent

Unified LLM subagent runner.

This skill replaces provider-specific subagent wrappers. It uses the same
provider adapter configuration as the unified main `driver` skill and supports
per-spawn provider/model overrides.

## Usage

```bash
python3 skills/subagent/run.py --provider openai --id sa-1 --parent-session main --task "Inspect auth flow"
python3 skills/subagent/run.py --provider anthropic --id sa-2 --parent-session main --task "Review this patch"
```

Optional `--model`, `--timeout`, and `--max-turns` behave like the old
provider-specific wrappers.
