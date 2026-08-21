## What this changes

<!-- One or two sentences. Link the issue if there is one. -->

## Why

<!-- The problem it solves. -->

## Checklist

- [ ] Tests cover the change (and fail without it)
- [ ] `ruff check .` passes
- [ ] `pytest -q` passes
- [ ] `CHANGELOG.md` updated under `## [Unreleased]`

## Protocol impact

- [ ] This does not change the wire format

If it does:

- [ ] `LIP_PROTOCOL_VERSION` bumped appropriately
- [ ] `python -m app.core.protocol.export_schemas` re-run and `schemas/` committed
- [ ] A matching RFC is open in the [specification repository](https://github.com/draiven-io/liquid-interfaces)
