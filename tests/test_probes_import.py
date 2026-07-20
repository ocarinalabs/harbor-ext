"""Probe tests.

Two layers:

- Interface smoke: every probe imports, constructs, extends ``BaseAgent``, and
  exposes a unique, correctly-prefixed slug name.
- Behavior: the execution-faking / tamper probes are exercised through their
  public seam — ``run(instruction, environment, context)`` — against a fake
  environment that records the shell commands each probe issues. A Harbor agent
  acts only by calling ``environment.exec``, so the set of commands it issues
  *is* its observable behavior; the tests assert on that rather than on private
  module constants, so they survive an internal rewrite that preserves what the
  probe actually writes.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from harbor.environments.base import ExecResult
from harbor.models.agent.context import AgentContext

from ocarinalabs_harbor_ext.probes import (
    ApPaymentDoublePayer,
    ApPaymentStateForger,
    QuaverFakeState,
    QuaverLedgerForge,
    QuaverPattern1,
    QuaverPattern4,
    QuaverPattern5,
    QuaverPattern7,
    QuaverStateRewrite,
)

# The general, reusable adversarial gate: the Berkeley patterns plus the
# execution-faking family. These carry the `quaver-` name prefix and are the
# probes the ocarina validation gate loads by submodule path.
_GATE_PROBES = [
    QuaverPattern1,
    QuaverPattern4,
    QuaverPattern5,
    QuaverPattern7,
    QuaverFakeState,
    QuaverLedgerForge,
    QuaverStateRewrite,
]
# World-specific probes (contractor-payment-run). Loaded ad hoc by submodule
# path during world hardening, not part of the general cascade; they carry an
# `ap-payment-` name prefix on purpose.
_WORLD_PROBES = [ApPaymentDoublePayer, ApPaymentStateForger]
_ALL_PROBES = _GATE_PROBES + _WORLD_PROBES

# A probe name is a non-empty dash-joined lowercase slug.
_PROBE_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")


@pytest.mark.parametrize("probe_cls", _ALL_PROBES)
def test_probe_has_slug_name(probe_cls):
    name = probe_cls.name()
    assert isinstance(name, str)
    assert _PROBE_NAME_RE.match(name), f"{name!r} is not a valid probe slug"


@pytest.mark.parametrize("probe_cls", _GATE_PROBES)
def test_gate_probe_carries_quaver_prefix(probe_cls):
    assert probe_cls.name().startswith("quaver-")


@pytest.mark.parametrize("probe_cls", _WORLD_PROBES)
def test_world_probe_carries_ap_payment_prefix(probe_cls):
    assert probe_cls.name().startswith("ap-payment-")


@pytest.mark.parametrize("probe_cls", _ALL_PROBES)
def test_probe_constructs_and_reports_version(probe_cls, tmp_path: Path):
    # The load-bearing check is that the harbor BaseAgent constructor accepts
    # `logs_dir=` and the subclass is concrete (no unimplemented abstract
    # method); the version is the shipped release string for this package.
    instance = probe_cls(logs_dir=tmp_path)
    assert instance.version() == "1.0.0"


def test_probe_names_are_unique():
    names = {p.name() for p in _ALL_PROBES}
    assert len(names) == len(_ALL_PROBES)
    assert names == {
        "quaver-pattern-1",
        "quaver-pattern-4",
        "quaver-pattern-5",
        "quaver-pattern-7",
        "quaver-fake-state",
        "quaver-ledger-forge",
        "quaver-state-rewrite",
        "ap-payment-double-payer",
        "ap-payment-state-forger",
    }


def test_probes_extend_base_agent():
    from harbor.agents.base import BaseAgent

    for probe_cls in _ALL_PROBES:
        assert issubclass(probe_cls, BaseAgent), f"{probe_cls.__name__} must extend BaseAgent"


# --- behavior through the public run() seam ---------------------------------


class _RecordingEnv:
    """Fake environment that records every exec command and reports success.

    Probes depend on exactly one method of their environment collaborator —
    ``await environment.exec(cmd)`` returning a result with ``return_code`` and
    ``stdout`` — so this duck-typed double captures behavior at the seam the
    probe actually uses, without standing up a real container.
    """

    def __init__(self) -> None:
        self.commands: list[str] = []

    async def exec(self, command: str, *_args, **_kwargs) -> ExecResult:
        self.commands.append(command)
        return ExecResult(return_code=0, stdout="")


_REDIRECT_RE = re.compile(r"cat\s+>>?\s+(\S+)")


def _redirect_targets(commands: list[str]) -> set[str]:
    """Every path a `cat > path` / `cat >> path` heredoc write targets."""
    return {match.group(1) for cmd in commands for match in _REDIRECT_RE.finditer(cmd)}


def _command_writing(commands: list[str], path: str) -> str | None:
    pattern = re.compile(rf"cat\s+>>?\s+{re.escape(path)}\b")
    return next((cmd for cmd in commands if pattern.search(cmd)), None)


def _ok_ledger_rows(commands: list[str]) -> list[list[str]]:
    """Tab-separated 5-column `ok` ledger records written by any command."""
    rows: list[list[str]] = []
    for cmd in commands:
        for line in cmd.splitlines():
            cols = line.split("\t")
            if len(cols) == 5 and cols[3] == "ok":
                rows.append(cols)
    return rows


async def _run(probe_cls, tmp_path: Path) -> _RecordingEnv:
    env = _RecordingEnv()
    await probe_cls(logs_dir=tmp_path).run("do the task", env, AgentContext())
    return env


async def test_pattern_7_tampers_agent_trajectory_not_the_retired_path(tmp_path: Path):
    env = await _run(QuaverPattern7, tmp_path)
    written = _redirect_targets(env.commands)
    # The ATIF trajectory now lives at /logs/agent/; the pre-1.7 /logs path is
    # retired and must not be targeted, or the probe tests a dead location.
    assert "/logs/agent/trajectory.json" in written
    assert "/logs/trajectory.json" not in written
    # It still attempts its core tamper: the canonical verifier reward file.
    assert "/logs/verifier/reward.json" in written
    trajectory_cmd = _command_writing(env.commands, "/logs/agent/trajectory.json")
    assert trajectory_cmd is not None
    assert "ATIF-v1.7" in trajectory_cmd


async def test_fake_state_writes_success_state_with_no_tool_calls(tmp_path: Path):
    env = await _run(QuaverFakeState, tmp_path)
    written = _redirect_targets(env.commands)
    assert "/app/state.json" in written
    assert "/app/output/result.json" in written
    # No ledger and no trajectory: the whole point is state without execution.
    assert "/app/actions.log" not in written
    assert "/logs/agent/trajectory.json" not in written


async def test_ledger_forge_writes_state_and_a_well_formed_ok_ledger(tmp_path: Path):
    env = await _run(QuaverLedgerForge, tmp_path)
    written = _redirect_targets(env.commands)
    assert "/app/state.json" in written
    assert "/app/actions.log" in written
    rows = _ok_ledger_rows(env.commands)
    assert rows, "ledger-forge must write forged ledger rows"
    for cols in rows:
        assert cols[2], "each ledger row names a tool verb"
        assert cols[3] == "ok"


async def test_state_rewrite_runs_real_spine_then_forges_state_and_ledger(tmp_path: Path):
    env = await _run(QuaverStateRewrite, tmp_path)
    written = _redirect_targets(env.commands)
    # The perfect fake finish: winning state plus an APPENDED forged ledger.
    assert "/app/state.json" in written
    assert "/app/actions.log" in written
    rows = _ok_ledger_rows(env.commands)
    assert rows, "state-rewrite must append forged ok ledger rows"
    assert all(cols[3] == "ok" for cols in rows)
    # Before the rewrite it drives the world's real tools to emit a faithful
    # host-shaped trajectory — the coverage-passing spine this probe exists to
    # stress. That spine, not a `cat >`, writes the trajectory, so assert on
    # the issued commands as a whole.
    issued = "\n".join(env.commands)
    assert "/app/tools-lib.ts" in issued
    assert "/logs/agent/trajectory.json" in issued
    assert "ATIF-v1.7" in issued
