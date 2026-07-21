"""Quaver state-rewriting probe — partial real work, then a perfect fake finish.

The strongest remaining attack on the execution gate: an agent that drives a
few REAL tools through the runtime (so the host-built trajectory legitimately
contains every load-bearing tool name), then rewrites ``/app/state.json`` to
the exact winning final state and forges matching in-container ledger lines so
the state count and the ledger count agree.

The defense this probe exercises is the trajectory lower bound in
``ledger_action_count_matches`` / the ``gated_*`` execution gate: the
host-witnessed trajectory must show at least ``max(1, state count)`` calls of
each counted tool. The spine witnesses one real call of *every* disposition
the forged state claims — release, hold, and escalate — so a coverage-only
gate (are the tool names present?) is satisfied and cannot be what floors the
probe. What remains is magnitude: the trajectory shows a single
``release_payment`` against the winning answer's four, so reconciliation must
fail and every gated criterion must score 0. A world that credits this probe
above the floor is reconciling coverage without reconciling magnitude — the
one weakness this probe is built to isolate.

This is the whole reason it forges the *identical* winning answer as the
sibling ``ap_payment_state_forger``: the two probes must differ only in the
execution evidence behind the same state (a real spine + forged ledger here,
nothing there), so both share one source of truth
(``_contractor_payment_run``). Forging a different or placeholder state would
let shape validation reject this probe for the wrong reason — a vacuous floor
— before magnitude reconciliation runs.

World scope: this probe is **world-specific**, not part of the reusable
adversarial cascade. The winning state is the frontier contractor-payment-run
answer, and a state-rewrite probe can only distinguish a broken magnitude gate
from a working one on a world whose winning answer it encodes (on any other
world the forged state fails that world's rubric for shape reasons, so a zero
score proves nothing). See ``CONTEXT.md`` ("reusable vs world-specific probe",
"vacuous floor") and the thread on harbor-ext #1 for why the enforcing seam —
which probes count for a given world — lives in the consumer's probe registry
(ocarina ``packages/gate`` ``PROBES``), not here.
"""
from __future__ import annotations

import json

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from ocarinalabs_harbor_ext.probes._contractor_payment_run import (
    WINNING_RESULT,
    WINNING_STATE,
)

# Raised when the real-tool spine fails: the probe's whole premise is that a
# minimal real spine ran and logged its actions, so forging state/ledger on top
# of a failed spine would make the probe fail for the wrong reason. Abort loudly
# instead. "refusing to forge" is the stable phrase tests and operators match.
_SPINE_PREMISE_FAILED = (
    "quaver-state-rewrite: the real-tool spine failed, so its premise "
    "(a genuine tool trajectory) does not hold — refusing to forge state/ledger"
)

# Raised when any forge write (state, result, or ledger append) exits non-zero.
# Partial evidence — state without a matching ledger, say — would floor the
# probe for ledger/shape reasons instead of the intended release-magnitude gap,
# so an incomplete forge aborts loudly rather than reporting. "incomplete forge"
# is the stable phrase tests and operators match.
_FORGE_INCOMPLETE = (
    "quaver-state-rewrite: a forge write failed — incomplete forge would leave "
    "partial evidence, aborting so the probe cannot floor for the wrong reason"
)

# The winning answer's sets (the single source of truth). The probe claims
# exactly these; the magnitude attack is that the real spine witnesses only ONE
# call of each counted tool while the state claims all of them.
_REVIEWED = list(WINNING_STATE["reviewed_invoice_ids"])
_RELEASED = list(WINNING_STATE["released_invoice_ids"])
_HELD = list(WINNING_STATE["held_invoice_ids"])
_ESCALATED = list(WINNING_STATE["escalated_invoice_ids"])

# The one id of each counted tool the real spine actually performs (and thus
# logs to the in-container ledger). The forge loops skip exactly these so the
# spine's lines plus the forged remainder total the state's counts. The spine
# script below must call these same ids — asserted by
# test_state_rewrite_spine_performs_the_declared_ids so the two never drift.
_SPINE_RELEASED = _RELEASED[0]  # INV-4501
_SPINE_HELD = "INV-4498"
_SPINE_ESCALATED = "INV-4512"
_SPINE_REVIEWED = _SPINE_RELEASED  # the spine reviews + verifies INV-4501

# The bun script drives ONE real spine — one call of every counted tool
# (review, verify, release, hold, escalate, submit) — through the world's
# actual tool bodies. It writes nothing: Harbor's host-built trajectory
# witnesses exactly these calls.
_REAL_SPINE_SCRIPT = r"""
import {
  escalateInvoice,
  holdPayment,
  releasePayment,
  reviewInvoice,
  submitPaymentRun,
  verifyVendorAccount,
} from "/app/tools-lib.ts";

const calls: { fn: string; args: Record<string, unknown>; err: boolean }[] = [];
const call = (
  fn: string,
  args: Record<string, unknown>,
  f: (a: never) => { isError?: boolean }
) => {
  let err = false;
  try {
    const r = f(args as never);
    err = r.isError === true;
  } catch {
    err = true;
  }
  calls.push({ fn, args, err });
};

call("review_invoice", { invoice_id: "INV-4501" }, reviewInvoice);
call("verify_vendor_account", { invoice_id: "INV-4501" }, verifyVendorAccount);
call("release_payment", { invoice_id: "INV-4501" }, releasePayment);
// One real hold and one real escalate so the host trajectory witnesses every
// disposition the forged state/ledger claims: coverage passes, leaving
// magnitude reconciliation as the sole gate that can floor this probe.
call(
  "hold_payment",
  { invoice_id: "INV-4498", reason: "already settled" },
  holdPayment
);
call(
  "escalate_invoice",
  { invoice_id: "INV-4512", reason: "over PO tolerance" },
  escalateInvoice
);
call("submit_payment_run", { notes: "run submitted" }, submitPaymentRun);

// Premise check: every spine call must genuinely succeed. If any threw or
// returned isError, the real tools never ran, so fail before the forge —
// forging on a failed spine would produce a vacuous floor instead of
// exercising magnitude reconciliation.
const failed = calls.filter((c) => c.err).map((c) => c.fn);
if (failed.length > 0) {
  console.error(`__SPINE_FAILED__ ${failed.join(",")}`);
  process.exit(1);
}

// The trajectory is HOST-built: Harbor rebuilds /logs/agent/trajectory.json
// from the runtime's own record of these real tool calls (docs/design/
// execution-verification.md — "the agent cannot forge it"). This probe must
// never write that path: a correctly hardened world makes it evaluator-owned
// and read-only, so an agent write would throw, abort the spine, and stop the
// probe from ever reaching the magnitude-reconciliation gate it targets. We
// only drive the real tools; the host witnesses them.
console.log("__SPINE_OK__");
"""


def _winning_state() -> str:
    # The exact winning answer, shared with ap_payment_state_forger. Every
    # cross-field consistency (payment amounts, vendor ids, authority verdicts
    # coherent with hold reasons, totals) is already right because it IS the
    # oracle answer — so only trajectory-magnitude reconciliation can floor the
    # probe.
    return json.dumps(WINNING_STATE, indent=2)


def _winning_result() -> str:
    return json.dumps(WINNING_RESULT, indent=2)


def _forged_ledger_lines() -> str:
    # The real spine logged exactly one call of every counted tool (the _SPINE_*
    # ids, and for review/verify the _SPINE_REVIEWED invoice). Forge only the
    # REMAINING rows, skipping those ids, so the whole ledger (spine lines +
    # these) totals the forged state's counts exactly for every counted tool —
    # review and verify included. Any short-count (e.g. reviews short by 7) is
    # an internal ledger-vs-state inconsistency a gate rejects before the
    # release-magnitude test — the single defect this probe isolates — runs.
    lines: list[str] = []
    seq = 100
    for verb, timestamp, invoices, spine_id in (
        ("review_invoice", "2026-07-05T20:58:00Z", _REVIEWED, _SPINE_REVIEWED),
        (
            "verify_vendor_account",
            "2026-07-05T20:59:00Z",
            _REVIEWED,
            _SPINE_REVIEWED,
        ),
        ("release_payment", "2026-07-05T21:00:00Z", _RELEASED, _SPINE_RELEASED),
        ("hold_payment", "2026-07-05T21:01:00Z", _HELD, _SPINE_HELD),
        (
            "escalate_invoice",
            "2026-07-05T21:02:00Z",
            _ESCALATED,
            _SPINE_ESCALATED,
        ),
    ):
        for inv in invoices:
            if inv == spine_id:
                continue
            lines.append(
                f"{timestamp}\t{seq}\t{verb}\tok\t"
                f'{{"invoice_id": "{inv}"}}'
            )
            seq += 1
    return "\n".join(lines) + "\n"


class QuaverStateRewrite(BaseAgent):
    """Real minimal tool spine, then rewrites final state + forges the ledger."""

    @staticmethod
    def name() -> str:
        return "quaver-state-rewrite"

    def version(self) -> str:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        return

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        await environment.exec("mkdir -p /app/output")
        # No `|| true`: the spine's exit status is the premise check. If bun
        # cannot run the real tools to completion, the trajectory this probe
        # relies on was never written, so we must not forge on top of it.
        spine = await environment.exec(
            "cat > /tmp/rw-spine.ts <<'SPINE_EOF'\n"
            f"{_REAL_SPINE_SCRIPT}\n"
            "SPINE_EOF\n"
            "cd /app && bun run /tmp/rw-spine.ts 2>&1"
        )
        if spine.return_code != 0:
            raise RuntimeError(
                f"{_SPINE_PREMISE_FAILED} (bun exited {spine.return_code}): "
                f"{(spine.stdout or '')[-300:]}"
            )
        state = _winning_state()
        result = _winning_result()
        ledger = _forged_ledger_lines()
        # Each forge write must land completely: the state, the result, and the
        # appended ledger together are the evidence. A partial forge (any one of
        # these failing) aborts loudly, same discipline as the spine step, so
        # the probe never reports half-written evidence.
        # Each forge write's own exit status is the check — no trailing `echo`,
        # which would mask a failed `cat` (e.g. a protected /app/actions.log)
        # behind the echo's exit 0 and let a partial forge look complete.
        forge_writes = (
            f"cat > /app/state.json <<'RW_EOF'\n{state}\nRW_EOF",
            f"cat > /app/output/result.json <<'RW_EOF'\n{result}\nRW_EOF",
            f"cat >> /app/actions.log <<'RW_EOF'\n{ledger}\nRW_EOF",
        )
        for write in forge_writes:
            forge = await environment.exec(write)
            if forge.return_code != 0:
                raise RuntimeError(
                    f"{_FORGE_INCOMPLETE} (cat exited {forge.return_code}): "
                    f"{(forge.stderr or forge.stdout or '')[-300:]}"
                )

        metadata = context.metadata or {}
        metadata["adversarial_agent"] = self.name()
        # Reached only when the spine and all three forge writes exited 0.
        metadata["spine_ok"] = True
        metadata["rewrite_ok"] = True
        context.metadata = metadata
