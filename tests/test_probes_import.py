"""Smoke tests: probes import cleanly and expose the expected Harbor agent interface."""
from __future__ import annotations

import pytest

from ocarinalabs_harbor_ext.probes import (
    QuaverPattern1,
    QuaverPattern4,
    QuaverPattern5,
    QuaverPattern7,
)

_ALL_PROBES = [QuaverPattern1, QuaverPattern4, QuaverPattern5, QuaverPattern7]


@pytest.mark.parametrize("probe_cls", _ALL_PROBES)
def test_probe_has_name(probe_cls):
    name = probe_cls.name()
    assert isinstance(name, str)
    assert name.startswith("quaver-pattern-")


@pytest.mark.parametrize("probe_cls", _ALL_PROBES)
def test_probe_has_version(probe_cls):
    instance = probe_cls()
    assert instance.version() == "1.0.0"


def test_probe_names_are_unique():
    names = {p.name() for p in _ALL_PROBES}
    assert len(names) == len(_ALL_PROBES)
    assert names == {
        "quaver-pattern-1",
        "quaver-pattern-4",
        "quaver-pattern-5",
        "quaver-pattern-7",
    }


def test_probes_extend_base_agent():
    from harbor.agents.base import BaseAgent

    for probe_cls in _ALL_PROBES:
        assert issubclass(probe_cls, BaseAgent), f"{probe_cls.__name__} must extend BaseAgent"
