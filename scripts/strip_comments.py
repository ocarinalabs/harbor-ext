#!/usr/bin/env python3
"""Remove full-line ``#`` comments from Python sources, idempotently.

Comment rot is the failure mode this exists for: rationale that was true once,
restated in five files, drifting out of step with the code. The rule this
package settled on is that a comment earns its place by explaining *why* an
attack works or why a defence is ordered as it is; anything else belongs in
``CONTEXT.md`` once, or nowhere.

Run it, read the diff, and put back what was load-bearing **with a keep
marker** on the block's first line::

    # strip-comments: keep
    # Create the parent first: not every Harbor environment pre-creates
    # /logs/agent, and a bare `cat >` dies on "no such file".

The marker is what makes rescuing safe. Without it a second run deletes the
rescued comment again — ocarina hit exactly that and lost a licensing
attribution on the re-run.

A module whose comments have all been reviewed can say so once, near the top,
instead of marking every block::

    # strip-comments: reviewed

Prefer that for curated modules; per-block markers are for a rescue that sits in
a file still worth stripping.

Never touched:

* docstrings — they are the module's and its public callables' interface
* trailing inline comments — short, attached to the line they qualify
* tool directives — ``noqa``, ``type: ignore``, ``pragma``, ``pylint``,
  ``mypy``, ``ruff``, encoding declarations, shebangs, licence headers
* comments inside string literals — embedded ``//`` and ``#`` script bodies are
  code, not commentary

Usage::

    python3 scripts/strip_comments.py --check src tests   # report only
    python3 scripts/strip_comments.py src tests           # rewrite
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import tokenize
from pathlib import Path

KEEP_MARKER = "strip-comments: keep"
REVIEWED_MARKER = "strip-comments: reviewed"

DIRECTIVE = re.compile(
    r"""
    ^\#\s*(?:
        !                       # shebang
      | -\*-                    # encoding declaration
      | (?:type|ruff|mypy|pylint|pyright|flake8|isort|black|coverage)\s*:
      | noqa\b
      | pragma\b
      | (?:SPDX|Copyright|License|LICENSE)\b
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _own_line_comments(source: str) -> list[tokenize.TokenInfo]:
    """Comment tokens that occupy a whole line, in source order.

    Tokenizing rather than matching ``^\\s*#`` is what keeps the ``#`` inside a
    shell heredoc or a TypeScript payload safe: the tokenizer sees those as part
    of a string literal, never as a comment.
    """
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    return [
        token
        for token in tokens
        if token.type == tokenize.COMMENT and not token.line[: token.start[1]].strip()
    ]


def strip(source: str) -> str:
    """Drop every own-line comment block that is not kept or a directive."""
    if REVIEWED_MARKER in source:
        return source
    doomed: set[int] = set()
    block_start: int | None = None
    block_kept = False

    for token in _own_line_comments(source):
        line_no = token.start[0]
        contiguous = block_start is not None and line_no == block_start + 1
        if not contiguous:
            block_kept = False
        block_start = line_no

        if DIRECTIVE.match(token.string.strip()):
            block_kept = True
        if KEEP_MARKER in token.string:
            block_kept = True
        if not block_kept:
            doomed.add(line_no)

    if not doomed:
        return source

    lines = source.splitlines(keepends=True)
    kept = [line for number, line in enumerate(lines, start=1) if number not in doomed]
    return "".join(kept)


def _python_files(roots: list[str]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        path = Path(root)
        found.extend([path] if path.is_file() else sorted(path.rglob("*.py")))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="files or directories to process")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report what would be stripped without rewriting",
    )
    args = parser.parse_args(argv)

    total = 0
    for path in _python_files(args.paths):
        source = path.read_text()
        stripped = strip(source)
        if stripped == source:
            continue
        removed = len(source.splitlines()) - len(stripped.splitlines())
        total += removed
        print(f"{path}: {removed} comment line(s)")
        if not args.check:
            path.write_text(stripped)

    verb = "would remove" if args.check else "removed"
    print(f"{verb} {total} comment line(s)")
    return 1 if (args.check and total) else 0


if __name__ == "__main__":
    sys.exit(main())
