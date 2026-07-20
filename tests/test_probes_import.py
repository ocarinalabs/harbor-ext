"""Smoke tests: probes import cleanly and expose the expected Harbor agent interface."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

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
from ocarinalabs_harbor_ext.probes.fake_state import _TARGETS
from ocarinalabs_harbor_ext.probes.ledger_forge import _TOOL_VERBS, _forged_ledger
from ocarinalabs_harbor_ext.probes.pattern_7 import _TAMPER_TARGETS

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
def test_probe_has_version(probe_cls, tmp_path: Path):
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


def test_pattern_7_targets_quaver_agent_trajectory_path():
    targets = dict(_TAMPER_TARGETS)
    assert "/logs/agent/trajectory.json" in targets
    assert "/logs/trajectory.json" not in targets
    assert targets["/logs/agent/trajectory.json"] == '{"schema_version":"ATIF-v1.7","steps":[]}'


def test_fake_state_targets_conventional_state_paths():
    paths = {path for path, _ in _TARGETS}
    assert "/app/state.json" in paths
    assert "/app/output/result.json" in paths


def test_ledger_forge_produces_well_formed_ok_lines():
    ledger = _forged_ledger()
    lines = [line for line in ledger.splitlines() if line]
    # Every forged line is a 5-column `ok` record for a known tool verb.
    assert lines, "forged ledger must not be empty"
    for line in lines:
        cols = line.split("\t")
        assert len(cols) == 5
        assert cols[2] in _TOOL_VERBS
        assert cols[3] == "ok"
