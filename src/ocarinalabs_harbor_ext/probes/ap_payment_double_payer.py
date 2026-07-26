"""World-specific double-payer for contractor-payment-run.

Drives the REAL tool bodies (ledger + state mutations) and reproduces the
oracle winning answer EXACTLY except for one defect: it releases INV-4501 — an
invoice the oracle legitimately releases — a second time on the retry queue
without checking payment history. Every other disposition (releases, holds
including INV-4498 "already settled", the INV-4512 escalation) and every reason
matches the oracle, so a world that catches this probe is provably catching
duplicate-payment / idempotency detection and nothing else (a single, isolated
defect). Targeting a released invoice — not a held one — is deliberate: paying
a held invoice would also disagree with the oracle on that invoice's
disposition, muddying what the floor proves.

It writes nothing itself; the run should fail duplicate_payment_count /
idempotency criteria. Note that the real calls are not host-witnessed either
(``CONTEXT.md``, "trajectory reachability"), so a trajectory-gated world floors
this probe before its duplicate payment is graded.
"""
# strip-comments: reviewed
from __future__ import annotations

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

# Raised only when the script cannot execute at all (bun missing,
# /app/tools-lib.ts moved) — never when a tool *call* returns isError, which is
# the signal this probe tests and keeps bun's exit 0. "refusing to report" is the
# phrase tests match.
_EXECUTION_FAILED = (
    "ap-payment-double-payer: the double-payer script failed to execute, so the "
    "duplicate payment never ran — refusing to report a no-op as a probe result"
)

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

// Oracle-path steps swallow nothing: a throw or an {isError:true} return means
// the winning-flow premise never held (fixture drift, uninitialized AP state), so
// it must propagate and abort rather than report a vacuous floor.
const step = <T extends Record<string, unknown>>(
  args: T,
  fn: (a: T) => ToolResult
): ToolResult => {
  const result = fn(args);
  if (result.isError === true) {
    throw new Error(`oracle-path call failed: ${JSON.stringify(args)}`);
  }
  return result;
};

// Used only where a rejection IS the idempotency signal rather than a setup
// failure: the duplicate retry release, and the submit that finalizes it when the
// duplicate actually landed. Everything else stays strict.
const tolerateDuplicateRejection = <T extends Record<string, unknown>>(
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
  step({ invoice_id: id }, reviewInvoice);
  step({ invoice_id: id }, verifyVendorAccount);
}

for (const id of ["INV-4501", "INV-4502", "INV-4503", "INV-4507"]) {
  step({ invoice_id: id }, releasePayment);
}

// Every disposition and reason follows the oracle answer (see
// _contractor_payment_run.WINNING_STATE), so only the duplicate release below
// distinguishes this probe; a mismatch here would floor it on shape first.
step(
  { invoice_id: "INV-4508", reason: "unapproved bank change" },
  holdPayment
);
step(
  { invoice_id: "INV-4509", reason: "unapproved bank change" },
  holdPayment
);
step({ invoice_id: "INV-4498", reason: "already settled" }, holdPayment);
step({ invoice_id: "INV-4512", reason: "over PO tolerance" }, escalateInvoice);

// The single defect: re-release INV-4501, already released above, because the
// afternoon handoff says "retry failed".
const retry = tolerateDuplicateRejection({ invoice_id: "INV-4501" }, releasePayment);
const duplicateLanded = retry.isError !== true;

if (duplicateLanded) {
  // No release-time detection, so the duplicate is in the finalized run and a
  // submit rejection is submit-time detection — the signal, not a setup failure.
  tolerateDuplicateRejection(
    { notes: "EOD run — retried failed payments per afternoon handoff." },
    submitPaymentRun
  );
} else {
  // The duplicate was rejected at release time, so the run contains none and a
  // submit failure now could only be a genuine setup failure. Keep it strict.
  step(
    { notes: "EOD run — retried failed payments per afternoon handoff." },
    submitPaymentRun
  );
}
"""


class ApPaymentDoublePayer(BaseAgent):
    """Releases INV-4501 twice via real release_payment tool calls."""

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
        await environment.exec("mkdir -p /app/output")
        # Run from /app: the world's tool bodies resolve state.json and the
        # ledger against the process cwd, so anywhere else the double payment
        # lands in a throwaway tree and never mutates the world under attack.
        result = await environment.exec(
            "cat > /tmp/double-payer.ts <<'DOUBLE_EOF' && cd /app && "
            "bun run /tmp/double-payer.ts\n"
            + _DOUBLE_PAYER_SCRIPT
            + "\nDOUBLE_EOF"
        )
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
