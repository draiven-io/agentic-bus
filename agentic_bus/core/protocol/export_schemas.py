"""Export the LIP wire format as JSON Schema.

The protocol is defined by the Pydantic models in :mod:`envelope`, but a
specification nobody can implement against is not a specification.  This
module serialises those models to JSON Schema under ``schemas/`` so that:

- implementers in other languages have a machine-readable contract;
- the published spec can reference generated artefacts instead of prose that
  drifts from the code;
- CI can assert the two never diverge (``--check``).

Usage::

    python -m agentic_bus.core.protocol.export_schemas           # write schemas/
    python -m agentic_bus.core.protocol.export_schemas --check   # verify, exit 1 on drift
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agentic_bus.core.protocol.envelope import (
    LIP_PROTOCOL_VERSION,
    PAYLOAD_TYPES,
    AgBusEnvelope,
    MessageType,
)

#: Where generated schemas land, relative to the repository root.
SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas"

_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_BASE_URI = "https://liquidinterfaces.org/schemas"


def _decorate(schema: dict[str, Any], slug: str, title: str) -> dict[str, Any]:
    """Add the identifying keywords Pydantic does not emit."""
    return {
        "$schema": _SCHEMA_DIALECT,
        "$id": f"{_BASE_URI}/{LIP_PROTOCOL_VERSION}/{slug}.json",
        "x-lip-version": LIP_PROTOCOL_VERSION,
        **schema,
        # After the spread: Pydantic emits the class name as the title, which
        # is an implementation detail rather than a protocol term.
        "title": title,
    }


def build_schemas() -> dict[str, dict[str, Any]]:
    """Return ``{filename: schema}`` for the envelope and every payload."""
    schemas: dict[str, dict[str, Any]] = {
        "envelope.json": _decorate(
            AgBusEnvelope.model_json_schema(),
            "envelope",
            "LIP Message Envelope",
        )
    }

    for message_type, model in PAYLOAD_TYPES.items():
        slug = f"{message_type.value}-payload"
        schemas[f"{slug}.json"] = _decorate(
            model.model_json_schema(),
            slug,
            f"LIP {message_type.value} payload",
        )

    schemas["index.json"] = {
        "$schema": _SCHEMA_DIALECT,
        "$id": f"{_BASE_URI}/{LIP_PROTOCOL_VERSION}/index.json",
        "title": "Liquid Interfaces Protocol schema index",
        "x-lip-version": LIP_PROTOCOL_VERSION,
        "envelope": "envelope.json",
        "payloads": {
            message_type.value: f"{message_type.value}-payload.json"
            for message_type in MessageType
        },
    }
    return schemas


def _serialise(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=False) + "\n"


def write(directory: Path) -> list[Path]:
    """Write every schema to *directory*, creating it if needed."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, schema in build_schemas().items():
        path = directory / filename
        path.write_text(_serialise(schema), encoding="utf-8")
        written.append(path)
    return written


def check(directory: Path) -> list[str]:
    """Return a list of human-readable drift descriptions (empty if clean)."""
    problems = []
    for filename, schema in build_schemas().items():
        path = directory / filename
        if not path.exists():
            problems.append(f"{filename}: missing")
            continue
        if path.read_text(encoding="utf-8") != _serialise(schema):
            problems.append(f"{filename}: out of date")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed schemas match the models; do not write",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=SCHEMA_DIR,
        help=f"output directory (default: {SCHEMA_DIR})",
    )
    args = parser.parse_args(argv)

    if args.check:
        problems = check(args.output)
        if problems:
            print("Protocol schemas are out of date:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            print(
                "\nRegenerate with: python -m agentic_bus.core.protocol.export_schemas",
                file=sys.stderr,
            )
            return 1
        print(f"Protocol schemas are up to date (LIP {LIP_PROTOCOL_VERSION}).")
        return 0

    written = write(args.output)
    print(f"Wrote {len(written)} schema(s) for LIP {LIP_PROTOCOL_VERSION} to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
