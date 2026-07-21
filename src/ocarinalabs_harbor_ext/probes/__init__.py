"""Quaver adversarial probes.

Probes corresponding to the Berkeley patterns for broken agent benchmarks,
plus the execution-faking family that targets the "wrote the answer, did no
work" loophole. Each probe is a standalone
:class:`~harbor.agents.base.BaseAgent` subclass. A benchmark that credits any
probe above the configured floor is not publication-ready.

- pattern_1 / pattern_7: isolation-boundary escapes and verifier-state tamper.
- pattern_4 / pattern_5: judge-injection and loose success-token credit.
- fake_state / ledger_forge: fabricate final state (and forge the in-container
  ledger) without calling tools — floored only by execution verification
  (trajectory coverage + reconciliation). See
  ``docs/design/execution-verification.md``.
- state_rewrite: the hybrid — drives a minimal REAL tool spine (coverage
  passes), then rewrites final state to the winning answer and forges the
  ledger to match. Floored only by the trajectory lower bound in
  reconciliation (host-witnessed calls >= claimed state delta).

The probes above form the general, reusable adversarial gate (``quaver-*``
names). Alongside them ship world-specific probes (``ap-payment-*`` names) that
encode the winning answer for one world — contractor-payment-run — and exist to
prove that world's execution gate holds against an answer-knowing adversary.
They are loaded ad hoc by submodule path during hardening, not run as part of
the general cascade.

The stock Harbor ``nop`` agent covers Berkeley's null-agent archetype; run it
alongside these for full coverage.
"""
from __future__ import annotations

from ocarinalabs_harbor_ext.probes.ap_payment_double_payer import ApPaymentDoublePayer
from ocarinalabs_harbor_ext.probes.ap_payment_state_forger import ApPaymentStateForger
from ocarinalabs_harbor_ext.probes.fake_state import QuaverFakeState
from ocarinalabs_harbor_ext.probes.ledger_forge import QuaverLedgerForge
from ocarinalabs_harbor_ext.probes.pattern_1 import QuaverPattern1
from ocarinalabs_harbor_ext.probes.pattern_4 import QuaverPattern4
from ocarinalabs_harbor_ext.probes.pattern_5 import QuaverPattern5
from ocarinalabs_harbor_ext.probes.pattern_7 import QuaverPattern7
from ocarinalabs_harbor_ext.probes.state_rewrite import QuaverStateRewrite

__all__ = [
    "ApPaymentDoublePayer",
    "ApPaymentStateForger",
    "QuaverFakeState",
    "QuaverLedgerForge",
    "QuaverPattern1",
    "QuaverPattern4",
    "QuaverPattern5",
    "QuaverPattern7",
    "QuaverStateRewrite",
]
