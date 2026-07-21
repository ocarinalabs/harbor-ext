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
import re
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


def _write_world(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "tools-lib.ts").write_text(_STUB_TOOLS_LIB)
    (root / "logs" / "agent").mkdir(parents=True, exist_ok=True)
    # The probe imports "/app/tools-lib.ts" absolutely and writes the
    # trajectory under /logs; point both at this sandbox so the script runs
    # without a container while still resolving state against its own cwd.
    script = _DOUBLE_PAYER_SCRIPT.replace(
        "/app/tools-lib.ts", str(root / "tools-lib.ts")
    ).replace("/logs/agent/trajectory.json", str(root / "logs/agent/trajectory.json"))
    script = re.sub(r'mkdirSync\("[^"]*/logs/agent"', f'mkdirSync("{root}/logs/agent"', script)
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
    assert state["released"].count("INV-4498") == 2


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
