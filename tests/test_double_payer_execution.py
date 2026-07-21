"""Integration coverage for the double-payer's landing behavior (finding 1).

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

# A realistic stand-in for the world's tools-lib: state resolves against the
# process cwd (like the shipped tools-lib's `${BASE_DIR}/state.json` default of
# /app when the run starts there), so releasing appends a payment record and
# counts a repeat release of an already-paid invoice as a duplicate.
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


# A world whose reviewInvoice throws: models a genuine SETUP failure on the
# oracle path (fixture drift / uninitialized state). It must abort the probe.
_THROWING_REVIEW_TOOLS = _STUB_TOOLS_LIB.replace(
    "export const reviewInvoice = (_a: { invoice_id: string }): ToolResult => ({});",
    "export const reviewInvoice = (_a: { invoice_id: string }): ToolResult => {\n"
    '  throw new Error("world state not initialized");\n};',
)

# A world whose reviewInvoice signals failure by VALUE ({isError:true}) rather
# than throwing: still a setup failure on the oracle path, which must abort.
_ISERROR_REVIEW_TOOLS = _STUB_TOOLS_LIB.replace(
    "export const reviewInvoice = (_a: { invoice_id: string }): ToolResult => ({});",
    "export const reviewInvoice = (_a: { invoice_id: string }): ToolResult => "
    "({ isError: true });",
)

# A world that rejects a DUPLICATE release by throwing (already-released id),
# while first-time releases succeed. This is the one expected rejection the
# probe must tolerate — its idempotency signal.
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


def _write_world(root: Path, tools_lib: str = _STUB_TOOLS_LIB) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "tools-lib.ts").write_text(tools_lib)
    # The probe imports "/app/tools-lib.ts" absolutely; point it at this sandbox
    # so the script runs without a container while still resolving state against
    # its own cwd. The script writes no trajectory, so no /logs rewrite needed.
    script = _DOUBLE_PAYER_SCRIPT.replace(
        "/app/tools-lib.ts", str(root / "tools-lib.ts")
    )
    (root / "double-payer.ts").write_text(script)


def test_double_payment_lands_when_run_from_the_world_root(tmp_path: Path) -> None:
    world = tmp_path / "app"
    _write_world(world)
    # Run from the world root (what `cd /app` guarantees in the container).
    subprocess.run(
        ["bun", "run", str(world / "double-payer.ts")],
        cwd=world,
        check=True,
        capture_output=True,
    )
    state = json.loads((world / "state.json").read_text())
    assert state["duplicate_payment_count"] == 1
    # The defect is a duplicate release of an oracle-RELEASED invoice (INV-4501);
    # the held INV-4498 is never released.
    assert state["released"].count("INV-4501") == 2
    assert "INV-4498" not in state["released"]


def test_double_payer_setup_failure_aborts_the_script(tmp_path: Path) -> None:
    world = tmp_path / "app"
    _write_world(world, tools_lib=_THROWING_REVIEW_TOOLS)
    # A throw on an oracle-path call (here reviewInvoice) is a setup failure:
    # the winning-flow premise never held, so it must NOT be swallowed. bun
    # exits non-zero, which run() turns into a loud _EXECUTION_FAILED abort
    # rather than reporting a vacuous floor.
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
    # An oracle-path tool that signals failure by VALUE ({isError:true}) rather
    # than by throwing is still a setup failure: `step` must treat it as one, so
    # bun exits non-zero and run() aborts — symmetric with throw propagation.
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
    # The world rejects the duplicate INV-4501 release by throwing; that single
    # expected rejection is the idempotency signal and must be tolerated, so the
    # script completes and bun exits 0.
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
    # The first (oracle-path) release landed; the duplicate was rejected.
    assert state["released"].count("INV-4501") == 1


def test_double_payment_misses_the_world_state_when_run_elsewhere(tmp_path: Path) -> None:
    world = tmp_path / "app"
    _write_world(world)
    stray = tmp_path / "stray"
    stray.mkdir()
    # Running from the wrong cwd writes state into the stray dir; the world's
    # own state.json is never created — the exact false-negative finding 1 warns
    # about, and the reason the probe must `cd /app`.
    subprocess.run(
        ["bun", "run", str(world / "double-payer.ts")],
        cwd=stray,
        check=True,
        capture_output=True,
    )
    assert not (world / "state.json").exists()
    assert (stray / "state.json").exists()
