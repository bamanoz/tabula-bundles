---
name: driver
description: "Unified Tabula main LLM driver. Selects OpenAI-compatible or Anthropic provider adapters at runtime. Usage: `python3 skills/driver/run.py --session <session> --provider openai|anthropic`."
---

# driver

Unified main-session LLM driver.

This skill replaces provider-specific main drivers for gateway sessions. It owns
main-driver provider configuration (`SKILL.config.json`, API keys, model
defaults) and dispatches to provider adapters in `skills/_drivers`.

## Usage

```bash
python3 skills/driver/run.py --session main --provider openai
python3 skills/driver/run.py --session main --provider anthropic
```

Optional `--model` overrides the configured provider model for this process.
