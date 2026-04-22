# drivers bundle

LLM driver and subagent skills plus their shared runtime helpers.

Ships:

- `driver-openai`      — OpenAI-compatible driver
- `driver-anthropic`   — Anthropic driver
- `subagent-openai`    — subagent skill (OpenAI)
- `subagent-anthropic` — subagent skill (Anthropic)
- `_drivers/`          — shared runtime (providers, driver_runtime,
                         subagent_runtime, prompt_builder, compaction,
                         provider_selection, config)

Anything in `_drivers/` is installed as a sibling `skills/_drivers/` inside the
distro, and skill code imports it as `skills._drivers.<module>`. This keeps
driver-specific code out of the core `skills/_lib/` contract.
