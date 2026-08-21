# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The **protocol** version (`LIP_PROTOCOL_VERSION`) is versioned separately
from this package; protocol changes are called out explicitly below.

## [Unreleased]

### Added

- `protocol_version` on every message envelope (LIP `0.1.0`). Envelopes from
  pre-versioning peers are read as `0.1.0`, so the change is backwards
  compatible on the wire.
- Generated JSON Schemas for the envelope and every payload under `schemas/`,
  produced by `python -m app.core.protocol.export_schemas`. CI fails if they
  drift from the Pydantic models.
- `LICENSE` (MIT). The README and package metadata claimed MIT, but no
  licence text was ever committed — until now the code was, strictly,
  all rights reserved.
- Continuous integration: ruff, the test suite on Python 3.11/3.12/3.13, the
  protocol schema check, and the dashboard build.
- `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, and issue/PR templates.
- `SECURITY.md` documents the known limitations of LLM-evaluated IBAC.

### Changed

- `agbus agent list` rejects an unknown `--status` instead of reporting an
  empty result, which made a typo indistinguishable from "no agents".
- Package metadata now describes the project as the reference implementation
  of the **Liquid Interfaces Protocol**, with homepage, repository, spec and
  paper URLs for PyPI.
- Code comments that referred to "the Agentic Bus paper" now name the
  Liquid Interfaces paper (`lip.md`) consistently.

### Fixed

- `resolve_tools` no longer aborts agent creation when an optional tool's
  dependency chain fails to import. Only `ValueError` and `ImportError` were
  caught, so an incompatible transitive dependency surfacing as
  `AttributeError` took down the whole agent instead of skipping one tool.
- The test suite is hermetic. It previously inherited the developer's `.env`
  through `load_dotenv(find_dotenv(usecwd=True))` at import time and shared
  the host database, so 19 tests passed locally and failed on a clean
  checkout. Every test now gets a scrubbed environment and its own migrated
  database (`tests/conftest.py`).
- The install-wizard tests could hang the run indefinitely: a drifted answer
  list fell through to the final "Start the coordinator server now?" prompt,
  which defaults to *yes*, and booted a real coordinator. Exhausting the
  answers now raises instead.
- Test assertions that still expected LLM settings in `.env` now assert
  against the database, where the wizard has been writing them.
