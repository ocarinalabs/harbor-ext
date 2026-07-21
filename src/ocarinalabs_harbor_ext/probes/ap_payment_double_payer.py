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

It writes nothing itself: Harbor's host-built trajectory witnesses the real
calls, so execution-gate coverage passes; the run should fail
duplicate_payment_count / idempotency criteria.
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

// The oracle-path steps run WITHOUT swallowing: if any throws, it is a genuine
// setup failure (fixture drift, uninitialized AP state), the winning-flow
// premise never held, and it must propagate so bun exits non-zero and run()
// aborts loudly rather than reporting a vacuous floor.
const step = <T extends Record<string, unknown>>(
  args: T,
  fn: (a: T) => ToolResult
): ToolResult => fn(args);

// ONLY the final duplicate release tolerates a throw: a world that rejects the
// duplicate by throwing (rather than returning {isError:true}) is signalling
// the idempotency outcome this probe tests, not an infra failure. Confining the
// catch to this one call mirrors the state-rewrite spine, which establishes its
// real-tool premise before the forged step.
const attemptDuplicate = <T extends Record<string, unknown>>(
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

// Every disposition and reason follows the oracle winning answer (see
// _contractor_payment_run.WINNING_STATE) — including holding INV-4498 as
// "already settled" — so only the duplicate release below distinguishes this
// probe; any disposition or reason mismatch would floor it on shape first.
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

// The single defect: naively re-release INV-4501 — an invoice already released
// above — because the afternoon handoff says "retry failed". A world with
// duplicate/idempotency detection catches exactly this, by isError or by
// throwing; either way it is the signal, not a setup failure, so it is the one
// call whose throw we tolerate.
attemptDuplicate({ invoice_id: "INV-4501" }, releasePayment);

step(
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
        await environment.exec("mkdir -p /app/output")
        # `&&`-chain the script write with its run so a failed/partial `cat`
        # heredoc can never fall through to executing a stale /tmp/double-payer.ts
        # (the exec exits non-zero instead). Run from /app: the world's tool
        # bodies resolve state.json and the actions ledger relative to the
        # process cwd, so the double payment only lands in the world under
        # attack when the script runs from the world root (matches the
        # state-rewrite spine).
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
