"""Ocarina adversarial probes.

Each probe is a standalone :class:`~harbor.agents.base.BaseAgent` subclass that
plays an adversary against a benchmark world. A benchmark that credits any probe
above the configured floor is not publication-ready. See ``README.md`` for what
each one catches and ``CONTEXT.md`` for the vocabulary.

Two families, distinguished by name prefix:

- ``ocarina-*`` — the general cascade, run against any Harbor world.
- ``ap-payment-*`` — world-specific, encoding the contractor-payment-run winning
  answer to prove that world's execution gate holds against an answer-knowing
  adversary. Loaded ad hoc during hardening, never as part of the cascade.

``state_rewrite`` carries the ``ocarina-`` prefix but is world-specific; the
consumer's registry, not this package, decides which probes count for a world.

The stock Harbor ``nop`` agent covers Berkeley's null-agent archetype; run it
alongside these for full coverage.
"""
from __future__ import annotations

from ocarinalabs_harbor_ext.probes.ap_payment_double_payer import ApPaymentDoublePayer
from ocarinalabs_harbor_ext.probes.ap_payment_state_forger import ApPaymentStateForger
from ocarinalabs_harbor_ext.probes.fake_state import OcarinaFakeState
from ocarinalabs_harbor_ext.probes.forbidden_subprocess import (
    OcarinaForbiddenSubprocess,
)
from ocarinalabs_harbor_ext.probes.isolation_escape import OcarinaIsolationEscape
from ocarinalabs_harbor_ext.probes.judge_injection import OcarinaJudgeInjection
from ocarinalabs_harbor_ext.probes.ledger_forge import OcarinaLedgerForge
from ocarinalabs_harbor_ext.probes.random_agent import OcarinaRandomAgent
from ocarinalabs_harbor_ext.probes.reward_sink import OcarinaRewardSink
from ocarinalabs_harbor_ext.probes.shortcut_hunter import OcarinaShortcutHunter
from ocarinalabs_harbor_ext.probes.state_rewrite import OcarinaStateRewrite
from ocarinalabs_harbor_ext.probes.success_token_echo import OcarinaSuccessTokenEcho

__all__ = [
    "ApPaymentDoublePayer",
    "ApPaymentStateForger",
    "OcarinaFakeState",
    "OcarinaForbiddenSubprocess",
    "OcarinaIsolationEscape",
    "OcarinaJudgeInjection",
    "OcarinaLedgerForge",
    "OcarinaRandomAgent",
    "OcarinaRewardSink",
    "OcarinaShortcutHunter",
    "OcarinaStateRewrite",
    "OcarinaSuccessTokenEcho",
]
