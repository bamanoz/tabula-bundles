# base bundle

A grab-bag of broadly useful skills that are not kernel-specific and not
bound to a particular distro:

- `clawhub`           — skill marketplace CLI
- `cron`              — time-based scheduler
- `hook-logger`       — persistent session/tool logs
- `hook-permissions`  — tool/command permission prompts
- `observer`          — passive session observer
- `pair`              — share an interactive session
- `sessions`          — listing / resuming local sessions
- `skill-contract`    — validate SKILL.md/config contract
- `tabula-guide`      — docs/help skill
- `timer`             — one-shot timers

A distro can take the whole bundle, or cherry-pick specific skills:

    [[bundles]]
    name   = "base"
    source = "git+https://github.com/bamanoz/tabula-bundles.git@main#path=base"
    skills = ["hook-logger", "hook-permissions"]  # optional allowlist
