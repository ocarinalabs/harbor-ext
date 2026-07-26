"""Integration coverage for the state-rewrite spine premise (Codex :127).

The seam tests assert `run()` aborts when the spine's `bun run` exits non-zero.
This module proves the spine script itself exits non-zero when a real tool
*call* fails — an import can succeed while a call throws or returns
`{isError: true}` (fixture drift, uninitialized AP state). Without that guard
the process exits 0, `run()` proceeds, and the probe forges an internally
inconsistent, vacuous floor instead of exercising magnitude reconciliation.

Skipped when ``bun`` is unavailable; the spine drives TypeScript tool bodies.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ocarinalabs_harbor_ext.probes.state_rewrite import _REAL_SPINE_SCRIPT

pytestmark = pytest.mark.skipif(
    shutil.which("bun") is None, reason="bun is required to execute world tools"
)

_ALL_OK_TOOLS = r"""
export const reviewInvoice = (_a: unknown) => ({});
export const verifyVendorAccount = (_a: unknown) => ({});
export const releasePayment = (_a: unknown) => ({});
export const holdPayment = (_a: unknown) => ({});
export const escalateInvoice = (_a: unknown) => ({});
export const submitPaymentRun = (_a: unknown) => ({});
"""

_RELEASE_ERRORS_TOOLS = _ALL_OK_TOOLS.replace(
    "export const releasePayment = (_a: unknown) => ({});",
    "export const releasePayment = (_a: unknown) => ({ isError: true });",
)


def _write_spine(root: Path, tools_lib: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "tools-lib.ts").write_text(tools_lib)
    (root / "logs" / "agent").mkdir(parents=True, exist_ok=True)
    script = _REAL_SPINE_SCRIPT.replace(
        "/app/tools-lib.ts", str(root / "tools-lib.ts")
    ).replace("/logs/agent", str(root / "logs" / "agent"))
    spine = root / "rw-spine.ts"
    spine.write_text(script)
    return spine


def test_spine_exits_zero_when_every_tool_call_succeeds(tmp_path: Path) -> None:
    spine = _write_spine(tmp_path / "app", _ALL_OK_TOOLS)
    result = subprocess.run(
        ["bun", "run", str(spine)],
        cwd=spine.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "__SPINE_OK__" in result.stdout


def test_spine_exits_nonzero_when_a_tool_call_fails(tmp_path: Path) -> None:
    spine = _write_spine(tmp_path / "app", _RELEASE_ERRORS_TOOLS)
    result = subprocess.run(
        ["bun", "run", str(spine)],
        cwd=spine.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "a failed spine call must fail the spine"
    assert "__SPINE_OK__" not in result.stdout
