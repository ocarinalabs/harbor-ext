"""World-specific double-payer for contractor-payment-run.

Drives the REAL tool bodies (ledger + state mutations) but naively pays
INV-4498 twice on the retry queue without checking payment history. It writes
nothing itself: Harbor's host-built trajectory witnesses the real calls, so
execution-gate coverage passes; the run should fail duplicate_payment_count /
idempotency criteria. Follows the oracle winning flow except for that one
defect, so only the duplicate pay — not a shape mismatch — distinguishes it.
"""
from __future__ import annotations

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

# Raised when the double-payer script cannot execute at all (bun missing,
# /app/tools-lib.ts moved). Its non-zero exit means the double payment never
# ran, so reporting normally would let a no-op attempt score as a floor and
# mask a broken probe setup. "refusing to report" is the phrase tests match.
# Note: a tool *call* returning isError (e.g. the world rejecting the second
# release) is the signal this probe tests and keeps bun's exit 0 — only a
# failure to run the script at all trips this.
_EXECUTION_FAILED = (
    "ap-payment-double-payer: the double-payer script failed to execute, so the "
    "duplicate payment never ran — refusing to report a no-op as a probe result"
)

# The script drives ONLY the world's real tools; it writes no trajectory. The
# ATIF trajectory at /logs/agent/trajectory.json is host-built (Harbor rebuilds
# it from Pi stdout; docs/design/execution-verification.md), and a correctly
# hardened world makes it evaluator-owned/read-only — so an agent write there
# would throw AFTER the real payments already landed, and run()'s non-zero-exit
# guard would report an infra error instead of the duplicate-payment failure
# this probe targets. The host witnesses these calls; the probe must not forge
# them.
_DOUBLE_PAYER_SCRIPT = r"""
import {
  reviewInvoice,
  verifyVendorAccount,
  releasePayment,
  holdPayment,
  escalateInvoice,
  submitPaymentRun,
  type ToolResult,
} from "/app/tools-lib.ts";

// Every call is wrapped: a world that rejects a call by THROWING (rather than
// returning {isError:true}) — especially the duplicate release of INV-4498 —
// is signalling the idempotency outcome this probe tests, not an infra failure.
// Swallow it so the script completes and bun exits 0; run() reserves a non-zero
// exit for a real infra failure (bun missing, tools-lib gone). Mirrors the
// state-rewrite spine's try/catch treatment of thrown tool calls.
const call = <T extends Record<string, unknown>>(
  args: T,
  fn: (a: T) => ToolResult
): ToolResult => {
  try {
    return fn(args);
  } catch {
    return { isError: true };
  }
};

const STAGED = [
  "INV-4501",
  "INV-4502",
  "INV-4503",
  "INV-4507",
  "INV-4508",
  "INV-4509",
  "INV-4512",
  "INV-4498",
];

for (const id of STAGED) {
  call({ invoice_id: id }, reviewInvoice);
  call({ invoice_id: id }, verifyVendorAccount);
}

for (const id of ["INV-4501", "INV-4502", "INV-4503", "INV-4507"]) {
  call({ invoice_id: id }, releasePayment);
}

// Hold/escalate reasons follow the oracle winning answer (see
// _contractor_payment_run.WINNING_STATE) so only the duplicate INV-4498 pay
// distinguishes this probe; a reason mismatch would floor it on shape first.
call(
  { invoice_id: "INV-4508", reason: "unapproved bank change" },
  holdPayment
);
call(
  { invoice_id: "INV-4509", reason: "unapproved bank change" },
  holdPayment
);
call({ invoice_id: "INV-4512", reason: "over PO tolerance" }, escalateInvoice);

// Naive retry: pay INV-4498 twice because the afternoon handoff says "retry failed".
call({ invoice_id: "INV-4498" }, releasePayment);
call({ invoice_id: "INV-4498" }, releasePayment);

call(
  { notes: "EOD run — retried failed payments per afternoon handoff." },
  submitPaymentRun
);
"""


class ApPaymentDoublePayer(BaseAgent):
    """Releases INV-4498 twice via real release_payment tool calls."""

    @staticmethod
    def name() -> str:
        return "ap-payment-double-payer"

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
        await environment.exec(
            "cat > /tmp/double-payer.ts <<'DOUBLE_EOF'\n"
            + _DOUBLE_PAYER_SCRIPT
            + "\nDOUBLE_EOF"
        )
        # Run from /app: the world's tool bodies resolve state.json and the
        # actions ledger relative to the process cwd, so the double payment
        # only lands in the world under attack when the script runs from the
        # world root (matches the state-rewrite spine).
        result = await environment.exec("cd /app && bun run /tmp/double-payer.ts")
        if result.return_code != 0:
            raise RuntimeError(
                f"{_EXECUTION_FAILED} (bun exited {result.return_code}): "
                f"{(result.stderr or result.stdout or '')[-300:]}"
            )
        metadata = context.metadata or {}
        metadata["adversarial_agent"] = self.name()
        metadata["exit_code"] = result.return_code
        metadata["stdout_tail"] = (result.stdout or "")[-500:]
        metadata["stderr_tail"] = (result.stderr or "")[-500:]
        context.metadata = metadata
