# Contributing to Agentic Bus

Agentic Bus is the reference implementation of the **Liquid Interfaces
Protocol (LIP)**. Protocol changes belong in the
[specification repository](https://github.com/draiven-io/liquid-interfaces);
runtime behaviour, the SDK, the dashboard and the CLI belong here.

## Getting set up

```bash
pip install -e ".[dev]"
```

```bash
pytest -q
```

The suite is **hermetic**: it ignores your `.env`, needs no API keys, and
never touches the network. If a test needs configuration, it provides its
own — see `tests/conftest.py`. A test that only passes on your machine is a
bug in the test.

Lint before pushing:

```bash
ruff check .
```

## Protocol changes

The wire format is defined by the Pydantic models in
`app/core/protocol/envelope.py`, and the JSON Schemas under `schemas/` are
**generated from them**:

```bash
python -m app.core.protocol.export_schemas
```

CI fails if the committed schemas drift from the models, so regenerate and
commit them in the same change. Anything that alters the wire format also
needs:

- a bump to `LIP_PROTOCOL_VERSION` (patch for editorial, minor for
  backwards-compatible additions, major for anything that breaks an existing
  implementation);
- a matching RFC in the specification repository.

Adding an optional field is a minor bump. Renaming or removing one, changing
a type, or adding a required field is a major bump — no exceptions, because
implementations in other languages have no way to discover the change
otherwise.

## Pull requests

- Branch from `main`; keep one logical change per PR.
- Every behavioural change needs a test that fails without it.
- Update `CHANGELOG.md` under `## [Unreleased]`.
- CI must be green: lint, tests on Python 3.11/3.12/3.13, schema check, UI build.

## Reporting bugs

Open an issue using the bug template. A reproduction — the intent text, the
registered agents, and the session transcript — is worth more than a
description, because most coordination failures depend on what the model
returned during negotiation.

For anything security-related, do **not** open an issue. See
[SECURITY.md](SECURITY.md).

## Code style

Match the surrounding code. The codebase favours explicit docstrings that
explain *why* a component exists and cite the relevant section of the paper
(`lip.md`) where one applies. Keep that convention: this is a reference
implementation, and the code is read as documentation of the protocol.
