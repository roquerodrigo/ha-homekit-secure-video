# Contributing

Bug reports, ideas and pull requests are welcome.

## Reporting a bug

Open an [issue](https://github.com/roquerodrigo/ha-homekit-secure-video/issues/new/choose) with:

- the Home Assistant version, the integration version and the camera model and integration;
- what you did, what you expected and what happened;
- the diagnostics downloaded from the device or integration page (the pairing code and setup code are redacted) and the debug log of the problem.

## Development setup

The project uses [uv](https://docs.astral.sh/uv/), which manages `.venv` for you.

```bash
scripts/setup      # install the dependencies into .venv
scripts/develop    # run Home Assistant at http://localhost:8123 with this integration loaded
```

`scripts/develop` uses the configuration in [`config/`](config/) and loads the integration from `custom_components/` through `PYTHONPATH`, without symlinks. To start over with fresh entity and device IDs, delete `config/.storage/core.entity_registry` and `config/.storage/core.device_registry`.

Recording can only be tested end to end with a real Apple home hub (HomePod or Apple TV) and an iCloud+ plan with a free camera slot. Everything below the hub is covered by the tests.

## Checks

Run these before opening a pull request. CI runs the same ones, along with the Home Assistant Marketplace, hassfest and HACS validations.

```bash
uv run ruff format .                                  # format
uv run ruff check . --fix                             # lint
uv run mypy custom_components/homekit_secure_video    # type-check
uv run pytest                                         # tests, coverage must stay at 90 % or more
```

`scripts/lint` runs the same four checks without changing any file (`ruff format --check` and `ruff check` without `--fix`).

`pre-commit install` runs ruff format, ruff check and mypy on every commit, along with basic file checks. The hooks use the tool versions pinned in `pyproject.toml` and `uv.lock`, the same ones CI uses.

Read [CODE_STYLE.md](CODE_STYLE.md) before adding or restructuring code, and [CLAUDE.md](CLAUDE.md) for the protocol and recording details that are not obvious from the code.

## Pull requests

1. Fork the repository and branch from `main`.
2. Write commit messages as [Conventional Commits](https://www.conventionalcommits.org/). Releases and their notes are generated from them. Mark breaking changes with `!` or a `BREAKING CHANGE:` footer.
3. Update `translations/en.json` and `translations/pt-BR.json` together when you change user-facing strings. `tests/test_translations.py` fails when their keys differ.
4. Update the README when behaviour, configuration or entities change.
5. Fill in the pull request template.

## License

Contributions are released under the project's [MIT License](LICENSE).
