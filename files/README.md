# files bundle

Provides the `files` skill — safe read/write/search of files under the workspace.

Each distro can include it via `distro.toml`:

    [[bundles]]
    name = "files"
    source = "git+https://github.com/bamanoz/tabula-bundles.git@main#path=files"
