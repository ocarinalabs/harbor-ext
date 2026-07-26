"""Tests for the comment stripper.

The stripper rewrites this repo's own sources, so its blast radius is the whole
package. What matters is not how many lines it removes but what it must never
remove: an interface docstring, a tool directive, a licence header, or a comment
someone deliberately rescued.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "strip_comments",
    Path(__file__).resolve().parent.parent / "scripts" / "strip_comments.py",
)
assert _SPEC is not None and _SPEC.loader is not None
strip_comments = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(strip_comments)
strip = strip_comments.strip


def test_removes_own_line_narration():
    assert strip("# narration\nX = 1\n") == "X = 1\n"


def test_keeps_a_docstring_even_when_it_contains_a_hash_line():
    source = '"""Doc.\n\n# not a comment\n"""\nX = 1\n'
    assert strip(source) == source


def test_keeps_trailing_inline_comments():
    source = "X = 1  # inline\n"
    assert strip(source) == source


def test_keeps_a_hash_inside_a_string_literal():
    """An embedded shell or TypeScript payload is code, not commentary."""
    source = 'SCRIPT = """\n# a shell comment\necho hi\n"""\n'
    assert strip(source) == source


def test_keeps_shebang_encoding_and_licence_header():
    source = (
        "#!/usr/bin/env python3\n"
        "# -*- coding: utf-8 -*-\n"
        "# Copyright (c) 2026 Ocarina Labs\n"
        "X = 1\n"
    )
    assert strip(source) == source


def test_keeps_tool_directives():
    for directive in (
        "# noqa: F401",
        "# ruff: noqa",
        "# type: ignore[misc]",
        "# pragma: no cover",
        "# pylint: disable=broad-except",
        "# mypy: ignore-errors",
    ):
        source = f"{directive}\nX = 1\n"
        assert strip(source) == source, directive


def test_a_directive_does_not_shield_the_narration_below_it():
    source = "# ruff: noqa\n# narration\nX = 1\n"
    assert strip(source) == "# ruff: noqa\nX = 1\n"


def test_keep_marker_rescues_its_whole_block():
    source = "# strip-comments: keep\n# why this matters\n# second line\nX = 1\n"
    assert strip(source) == source


def test_keep_marker_does_not_rescue_a_later_separate_block():
    source = (
        "# strip-comments: keep\n"
        "# rescued\n"
        "X = 1\n"
        "\n"
        "# narration\n"
        "Y = 2\n"
    )
    assert strip(source) == "# strip-comments: keep\n# rescued\nX = 1\n\nY = 2\n"


def test_reviewed_marker_exempts_the_whole_module():
    source = "# strip-comments: reviewed\n# curated rationale\nX = 1\n"
    assert strip(source) == source


def test_is_idempotent():
    source = (
        "#!/usr/bin/env python3\n"
        '"""Doc."""\n'
        "# narration\n"
        "# strip-comments: keep\n"
        "# rescued\n"
        "X = 1  # inline\n"
    )
    once = strip(source)
    assert strip(once) == once


def test_the_shipped_sources_are_already_stripped():
    """A re-run must be a no-op, or the tree and the tool disagree."""
    root = Path(__file__).resolve().parent.parent
    for path in sorted((root / "src").rglob("*.py")) + sorted(
        (root / "tests").rglob("*.py")
    ):
        source = path.read_text()
        assert strip(source) == source, f"{path} still has strippable comments"
