"""Integration coverage for the double-payer's landing behavior.

The seam tests in ``test_probes_import.py`` assert the probe *issues* a
``cd /app`` before running its script. This module proves *why* that matters:
executed against a realistic world whose tool bodies resolve state relative to
the process working directory, the double payment only lands in the world's
state file when the script runs from the world root. Running from the wrong
directory writes a throwaway state and the world under attack is never mutated
— a false-negative probe.

Skipped when ``bun`` is unavailable; the harness world tools are TypeScript.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ocarinalabs_harbor_ext.probes.ap_payment_double_payer import (
    _DOUBLE_PAYER_SCRIPT,
)

pytestmark = pytest.mark.skipif(
    shutil.which("bun") is None, reason="bun is required to execute world tools"
)

_STUB_TOOLS_LIB = r"""
import { appendFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";

export type ToolResult = { readonly isError?: boolean };

const STATE = `${process.cwd()}/state.json`;

const load = (): {
  released: string[];
  duplicate_payment_count: number;
} => {
  if (!existsSync(STATE)) {
    return { released: [], duplicate_payment_count: 0 };
  }
  return JSON.parse(readFileSync(STATE, "utf-8"));
};

const save = (s: unknown): void => writeFileSync(STATE, JSON.stringify(s, null, 2));

export const reviewInvoice = (_a: { invoice_id: string }): ToolResult => ({});
export const verifyVendorAccount = (_a: { invoice_id: string }): ToolResult => ({});
export const holdPayment = (_a: { invoice_id: string; reason: string }): ToolResult => ({});
export const escalateInvoice = (_a: { invoice_id: string; reason: string }): ToolResult => ({});
export const submitPaymentRun = (_a: { notes?: string }): ToolResult => ({});

export const releasePayment = (a: { invoice_id: string }): ToolResult => {
  const s = load();
  if (s.released.includes(a.invoice_id)) {
    s.duplicate_payment_count += 1;
  }
  s.released.push(a.invoice_id);
  save(s);
  return {};
};
"""


_THROWING_REVIEW_TOOLS = _STUB_TOOLS_LIB.replace(
    "export const reviewInvoice = (_a: { invoice_id: string }): ToolResult => ({});",
    "export const reviewInvoice = (_a: { invoice_id: string }): ToolResult => {\n"
    '  throw new Error("world state not initialized");\n};',
)

_ISERROR_REVIEW_TOOLS = _STUB_TOOLS_LIB.replace(
    "export const reviewInvoice = (_a: { invoice_id: string }): ToolResult => ({});",
    "export const reviewInvoice = (_a: { invoice_id: string }): ToolResult => "
    "({ isError: true });",
)

_DUPLICATE_REJECTING_TOOLS = _STUB_TOOLS_LIB.replace(
    "  const s = load();\n"
    "  if (s.released.includes(a.invoice_id)) {\n"
    "    s.duplicate_payment_count += 1;\n"
    "  }\n"
    "  s.released.push(a.invoice_id);\n"
    "  save(s);\n"
    "  return {};",
    "  const s = load();\n"
    "  if (s.released.includes(a.invoice_id)) {\n"
    '    throw new Error("duplicate payment rejected");\n'
    "  }\n"
    "  s.released.push(a.invoice_id);\n"
    "  save(s);\n"
    "  return {};",
)

_SUBMIT_TIME_THROW_TOOLS = _STUB_TOOLS_LIB.replace(
    "export const submitPaymentRun = (_a: { notes?: string }): ToolResult => ({});",
    "export const submitPaymentRun = (_a: { notes?: string }): ToolResult => {\n"
    "  const s = load();\n"
    "  if (s.duplicate_payment_count > 0) {\n"
    '    throw new Error("payment run contains a duplicate payment");\n'
    "  }\n"
    "  return {};\n};",
)

_SUBMIT_TIME_ISERROR_TOOLS = _STUB_TOOLS_LIB.replace(
    "export const submitPaymentRun = (_a: { notes?: string }): ToolResult => ({});",
    "export const submitPaymentRun = (_a: { notes?: string }): ToolResult => {\n"
    "  const s = load();\n"
    "  if (s.duplicate_payment_count > 0) {\n"
    "    return { isError: true };\n"
    "  }\n"
    "  return {};\n};",
)

_RELEASE_REJECTED_THEN_SUBMIT_FAILS_TOOLS = _DUPLICATE_REJECTING_TOOLS.replace(
    "export const submitPaymentRun = (_a: { notes?: string }): ToolResult => ({});",
    "export const submitPaymentRun = (_a: { notes?: string }): ToolResult => {\n"
    '  throw new Error("submit-time validation failed (unrelated to duplicates)");\n'
    "};",
)


def _write_world(root: Path, tools_lib: str = _STUB_TOOLS_LIB) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "tools-lib.ts").write_text(tools_lib)
    script = _DOUBLE_PAYER_SCRIPT.replace(
        "/app/tools-lib.ts", str(root / "tools-lib.ts")
    )
    (root / "double-payer.ts").write_text(script)


def test_double_payment_lands_when_run_from_the_world_root(tmp_path: Path) -> None:
    world = tmp_path / "app"
    _write_world(world)
    subprocess.run(
        ["bun", "run", str(world / "double-payer.ts")],
        cwd=world,
        check=True,
        capture_output=True,
    )
    state = json.loads((world / "state.json").read_text())
    assert state["duplicate_payment_count"] == 1
    assert state["released"].count("INV-4501") == 2
    assert "INV-4498" not in state["released"]


def test_double_payer_setup_failure_aborts_the_script(tmp_path: Path) -> None:
    world = tmp_path / "app"
    _write_world(world, tools_lib=_THROWING_REVIEW_TOOLS)
    result = subprocess.run(
        ["bun", "run", str(world / "double-payer.ts")],
        cwd=world,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        f"a setup-path throw must abort the probe; stderr: {result.stderr}"
    )


def test_double_payer_setup_iserror_return_aborts_the_script(tmp_path: Path) -> None:
    world = tmp_path / "app"
    _write_world(world, tools_lib=_ISERROR_REVIEW_TOOLS)
    result = subprocess.run(
        ["bun", "run", str(world / "double-payer.ts")],
        cwd=world,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        f"an oracle-path isError return must abort the probe; stderr: {result.stderr}"
    )


def test_double_payer_tolerates_only_the_duplicate_rejection(tmp_path: Path) -> None:
    world = tmp_path / "app"
    _write_world(world, tools_lib=_DUPLICATE_REJECTING_TOOLS)
    result = subprocess.run(
        ["bun", "run", str(world / "double-payer.ts")],
        cwd=world,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"the expected duplicate rejection must not abort; stderr: {result.stderr}"
    )
    state = json.loads((world / "state.json").read_text())
    assert state["released"].count("INV-4501") == 1


def test_double_payer_tolerates_submit_time_duplicate_rejection(tmp_path: Path) -> None:
    world = tmp_path / "app"
    _write_world(world, tools_lib=_SUBMIT_TIME_THROW_TOOLS)
    result = subprocess.run(
        ["bun", "run", str(world / "double-payer.ts")],
        cwd=world,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"a submit-time duplicate rejection must not abort; stderr: {result.stderr}"
    )
    state = json.loads((world / "state.json").read_text())
    assert state["duplicate_payment_count"] == 1
    assert state["released"].count("INV-4501") == 2


def test_double_payer_tolerates_submit_time_iserror_rejection(tmp_path: Path) -> None:
    world = tmp_path / "app"
    _write_world(world, tools_lib=_SUBMIT_TIME_ISERROR_TOOLS)
    result = subprocess.run(
        ["bun", "run", str(world / "double-payer.ts")],
        cwd=world,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"a submit-time isError rejection must not abort; stderr: {result.stderr}"
    )


def test_double_payer_keeps_submit_strict_after_release_time_rejection(
    tmp_path: Path,
) -> None:
    world = tmp_path / "app"
    _write_world(world, tools_lib=_RELEASE_REJECTED_THEN_SUBMIT_FAILS_TOOLS)
    result = subprocess.run(
        ["bun", "run", str(world / "double-payer.ts")],
        cwd=world,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        "a submit failure after a release-time duplicate rejection must abort; "
        f"stderr: {result.stderr}"
    )


def test_double_payment_misses_the_world_state_when_run_elsewhere(tmp_path: Path) -> None:
    world = tmp_path / "app"
    _write_world(world)
    stray = tmp_path / "stray"
    stray.mkdir()
    subprocess.run(
        ["bun", "run", str(world / "double-payer.ts")],
        cwd=stray,
        check=True,
        capture_output=True,
    )
    assert not (world / "state.json").exists()
    assert (stray / "state.json").exists()
