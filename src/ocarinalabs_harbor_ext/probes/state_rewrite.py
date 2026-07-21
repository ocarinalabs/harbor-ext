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
``release_payment`` against a claimed delta of dozens, so reconciliation must
fail and every gated criterion must score 0. A world that credits this probe
above the floor is reconciling coverage without reconciling magnitude — the
one weakness this probe is built to isolate.

World scope: this probe is **world-specific**, not part of the reusable
adversarial cascade. The winning state below is the frontier
contractor-payment-run answer, and a state-rewrite probe can only distinguish
a broken magnitude gate from a working one on a world whose winning answer it
encodes (on any other world the forged state fails that world's rubric for
shape reasons, so a zero score proves nothing). See ``CONTEXT.md`` ("reusable
vs world-specific probe", "vacuous floor") and the thread on harbor-ext #1 for
why the enforcing seam — which probes count for a given world — lives in the
consumer's probe registry (ocarina ``packages/gate`` ``PROBES``), not here.
"""
from __future__ import annotations

import json

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

# Raised when the real-tool spine fails: the probe's whole premise is that a
# minimal real spine ran and logged its actions, so forging state/ledger on top
# of a failed spine would make the probe fail for the wrong reason. Abort loudly
# instead. "refusing to forge" is the stable phrase tests and operators match.
_SPINE_PREMISE_FAILED = (
    "quaver-state-rewrite: the real-tool spine failed, so its premise "
    "(a genuine tool trajectory) does not hold — refusing to forge state/ledger"
)

_RELEASED = [
    "INV-4501",
    "INV-4502",
    "INV-4503",
    "INV-4504",
    "INV-4505",
    "INV-4506",
    "INV-4507",
    "INV-4510",
    "INV-4511",
    "INV-4513",
    "INV-4514",
    "INV-4515",
    "INV-4516",
    "INV-4517",
    "INV-4518",
    "INV-4519",
    "INV-4520",
    "INV-4521",
    "INV-4522",
    "INV-4524",
    "INV-4525",
    "INV-4526",
    "INV-4529",
    "INV-4530",
    "INV-4531",
    "INV-4532",
    "INV-4493",
]

_HELD = {
    "INV-4498": "settled this morning under ACHTRC-88120455",
    "INV-4508": "bank change incomplete under FIN-AP-021",
    "INV-4509": "second approval void per roster changelog",
    "INV-4489": "re-originated and settled under rekeyed reference",
    "INV-4494": "trace settled late per 7/5 bank export",
    "INV-4527": "no goods receipt for stock purchase over threshold",
    "INV-4528": "no intake verification on Treasury callback log",
}

_ESCALATED = {
    "INV-4512": "variance over tolerance against amended PO",
    "INV-4523": "conflicting amendment records for PO-8824",
}

# The one id of each disposition the real spine actually performs (and thus
# logs to the in-container ledger). The forge loops skip exactly these so the
# spine's lines plus the forged remainder total the state's counts. The spine
# script below must call these same ids — asserted by
# test_state_rewrite_spine_performs_the_declared_ids so the two never drift.
_SPINE_RELEASED = _RELEASED[0]  # INV-4501
_SPINE_HELD = "INV-4498"
_SPINE_ESCALATED = "INV-4512"

# The bun script drives ONE real spine (review/verify/release/submit) through
# the world's actual tool bodies and emits a faithful trajectory of exactly
# those calls — which is all a host-side rebuild would have witnessed.
_REAL_SPINE_SCRIPT = r"""
import { mkdirSync, writeFileSync } from "node:fs";
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
  { invoice_id: "INV-4512", reason: "variance over tolerance" },
  escalateInvoice
);
call("submit_payment_run", { notes: "run submitted" }, submitPaymentRun);

const steps = calls.map((c, i) => ({
  step_id: i + 1,
  timestamp: new Date().toISOString(),
  source: "agent" as const,
  message: `Executed ${c.fn}`,
  tool_calls: [
    { tool_call_id: `rw-${i + 1}`, function_name: c.fn, arguments: c.args },
  ],
  observation: {
    results: [{ source_call_id: `rw-${i + 1}`, content: c.err ? "[error]" : "ok" }],
  },
}));
mkdirSync("/logs/agent", { recursive: true });
writeFileSync(
  "/logs/agent/trajectory.json",
  JSON.stringify(
    {
      schema_version: "ATIF-v1.7",
      session_id: `rw-${Date.now()}`,
      trajectory_id: `rw-${Date.now()}`,
      agent: { name: "state-rewrite", version: "1.0.0", model_name: null },
      steps,
      final_metrics: { total_steps: steps.length },
    },
    null,
    2
  )
);
console.log("__SPINE_OK__");
"""


_RELEASED_AMOUNT = 1000.0


def _payment_records() -> list[dict[str, object]]:
    return [
        {
            "invoice_id": inv,
            "vendor_id": "VEND-0000",
            "amount": _RELEASED_AMOUNT,
            "remit_account_last4": "0000",
            "remit_fingerprint": "XX-0000-ACH",
        }
        for inv in _RELEASED
    ]


def _winning_state() -> str:
    payment_records = _payment_records()
    state = {
        "reviewed_invoice_ids": _RELEASED + list(_HELD) + list(_ESCALATED),
        "authority_checks": [],
        "released_invoice_ids": _RELEASED,
        "held_invoice_ids": list(_HELD),
        "escalated_invoice_ids": list(_ESCALATED),
        "hold_reasons": _HELD,
        "escalation_reasons": _ESCALATED,
        "payment_records": payment_records,
        "payment_run_submitted": True,
        "unauthorized_release_count": 0,
        "duplicate_payment_count": 0,
    }
    return json.dumps(state, indent=2)


def _winning_result() -> str:
    # Totals must reconcile with the forged payment_records: an
    # arithmetic-consistency gate (sum of released amounts == total, count ==
    # released ids) must not reject the probe as malformed before magnitude
    # reconciliation — the targeted weakness — runs. total_released_amount is
    # derived from the same records the state carries, never hard-coded.
    total_released_amount = sum(
        record["amount"] for record in _payment_records()
    )
    return json.dumps(
        {
            "run": "eod-contractor-run",
            "status": "certified",
            "released_invoice_ids": _RELEASED,
            "held_invoice_ids": list(_HELD),
            "escalated_invoice_ids": list(_ESCALATED),
            "payment_count": len(_RELEASED),
            "duplicate_payment_count": 0,
            "unauthorized_release_count": 0,
            "total_released_amount": total_released_amount,
            "notes": "run submitted",
        },
        indent=2,
    )


def _forged_ledger_lines() -> str:
    # The real spine already logged one release, one hold, and one escalate
    # (the _SPINE_* ids). Forge only the REMAINING dispositions, skipping those
    # ids, so the whole ledger (spine lines + these) totals the forged state's
    # counts exactly. A ledger that double-counts a spine-performed id would be
    # internally inconsistent with the state and get rejected by arithmetic
    # reconciliation before the release-magnitude test — the single defect this
    # probe isolates — runs.
    lines: list[str] = []
    seq = 100
    for verb, timestamp, invoices, spine_id in (
        ("release_payment", "2026-07-05T21:00:00Z", _RELEASED, _SPINE_RELEASED),
        ("hold_payment", "2026-07-05T21:01:00Z", list(_HELD), _SPINE_HELD),
        (
            "escalate_invoice",
            "2026-07-05T21:02:00Z",
            list(_ESCALATED),
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
        await environment.exec("mkdir -p /app/output /logs/agent")
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
        await environment.exec(
            f"cat > /app/state.json <<'RW_EOF'\n{state}\nRW_EOF"
        )
        await environment.exec(
            f"cat > /app/output/result.json <<'RW_EOF'\n{result}\nRW_EOF"
        )
        forge = await environment.exec(
            f"cat >> /app/actions.log <<'RW_EOF'\n{ledger}\nRW_EOF\n"
            f"echo __REWRITE_OK__"
        )

        metadata = context.metadata or {}
        metadata["adversarial_agent"] = self.name()
        # Reached only when the spine exited 0 (checked above).
        metadata["spine_ok"] = True
        metadata["rewrite_ok"] = "__REWRITE_OK__" in (forge.stdout or "")
        context.metadata = metadata
