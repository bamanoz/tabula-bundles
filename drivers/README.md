# drivers bundle

LLM driver and subagent skills plus their shared runtime helpers.

Ships:

- `driver`             — unified main-session driver; selects provider adapter at runtime
- `subagent`           — unified subagent runner; selects provider adapter at runtime
- `_drivers/`          — shared runtime (providers, driver_runtime,
                         subagent_runtime, prompt_builder, compaction,
                         provider_selection, config)

Anything in `_drivers/` is installed as a sibling `skills/_drivers/` inside the
distro, and skill code imports it as `skills._drivers.<module>`. This keeps
driver-specific code out of the core `skills/_pylib/` contract.
