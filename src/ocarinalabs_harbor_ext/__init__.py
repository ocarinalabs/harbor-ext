"""Ocarina Labs' Harbor extension.

Adversarial probes for benchmark integrity, packaged for stock Harbor.

Import probes directly:

    from ocarinalabs_harbor_ext.probes import QuaverPattern1

Or load via Harbor's ``--agent-import-path`` mechanism:

    harbor run <world> \\
      --agent-import-path ocarinalabs_harbor_ext.probes.pattern_1:QuaverPattern1
"""
from __future__ import annotations

__version__ = "0.1.0"
