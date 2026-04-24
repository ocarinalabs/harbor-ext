"""Quaver adversarial probes.

Four probes corresponding to four of the seven Berkeley patterns for broken
agent benchmarks. Each probe is a standalone :class:`~harbor.agents.base.BaseAgent`
subclass. A benchmark that credits any probe above the configured floor is not
publication-ready.

The stock Harbor ``nop`` agent covers Berkeley's null-agent archetype; run it
alongside these four for full coverage.
"""
from __future__ import annotations

from ocarinalabs_harbor_ext.probes.pattern_1 import QuaverPattern1
from ocarinalabs_harbor_ext.probes.pattern_4 import QuaverPattern4
from ocarinalabs_harbor_ext.probes.pattern_5 import QuaverPattern5
from ocarinalabs_harbor_ext.probes.pattern_7 import QuaverPattern7

__all__ = [
    "QuaverPattern1",
    "QuaverPattern4",
    "QuaverPattern5",
    "QuaverPattern7",
]
