"""Docstrings cite AGENTS.md by section number; those citations must resolve.

They stopped resolving once before: AGENTS.md was committed, later removed,
and nine modules went on citing sections of a file that was not in the
repository. Nothing failed, so nobody noticed — which is exactly the kind of
rot a test should catch rather than a reader.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENTS_MD = REPO_ROOT / "AGENTS.md"
PACKAGE = REPO_ROOT / "agentic_bus"

#: "§12 of AGENTS.md" and "AGENTS.md §12" are both in use.
CITATION_PATTERNS = (
    re.compile(r"§\s*(\d+)(?:\.\d+)*[^\n]{0,40}?AGENTS\.md"),
    re.compile(r"AGENTS\.md\s*§\s*(\d+)(?:\.\d+)*"),
)


def _sections() -> dict[int, str]:
    text = AGENTS_MD.read_text(encoding="utf-8")
    return {
        int(m.group(1)): m.group(2)
        for m in re.finditer(r"^## (\d+)\. (.+)$", text, re.MULTILINE)
    }


def _citations() -> list[tuple[pathlib.Path, int]]:
    found: list[tuple[pathlib.Path, int]] = []
    for path in PACKAGE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in CITATION_PATTERNS:
            for match in pattern.finditer(text):
                found.append((path.relative_to(REPO_ROOT), int(match.group(1))))
    return found


def test_agents_md_exists():
    assert AGENTS_MD.is_file(), (
        "AGENTS.md is missing, but modules cite it by section number. "
        "It was deleted once before and the citations silently dangled."
    )


def test_agents_md_sections_are_sequential():
    """Gaps mean a section was renumbered, which invalidates citations."""
    numbers = sorted(_sections())
    assert numbers, "AGENTS.md has no numbered sections"
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"section numbering has gaps: {numbers}. Docstrings cite these by "
        "number, so add sections at the end rather than renumbering."
    )


def test_every_citation_resolves():
    sections = _sections()
    dangling = [
        (str(path), number)
        for path, number in _citations()
        if number not in sections
    ]
    assert dangling == [], (
        f"docstrings cite AGENTS.md sections that do not exist: {dangling}"
    )


def test_there_are_citations_to_check():
    """Guards the test itself: a regex that stops matching would pass
    vacuously and quietly stop protecting anything."""
    assert len(_citations()) >= 5, (
        "found almost no AGENTS.md citations — the patterns above have "
        "probably drifted from how the codebase writes them"
    )


@pytest.mark.parametrize(
    "stale",
    [
        "agbus.md",          # the paper is lip.md
        "langchain==1.2.9",  # the pin is a range, resolved at runtime
    ],
)
def test_known_stale_references_stay_gone(stale):
    assert stale not in AGENTS_MD.read_text(encoding="utf-8")
