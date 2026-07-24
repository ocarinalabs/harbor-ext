"""Ocarina Labs' Harbor extension.

Adversarial probes for benchmark integrity, packaged for stock Harbor.

Import probes directly:

    from ocarinalabs_harbor_ext.probes import OcarinaIsolationEscape

Or load via Harbor's unified ``--agent`` mechanism:

    harbor run <world> \\
      --agent ocarinalabs_harbor_ext.probes.isolation_escape:OcarinaIsolationEscape
"""
from __future__ import annotations

__version__ = "0.1.0"
