"""Quaver ledger-forging probe — fakes state AND the in-container ledger.

The tool side-effect ledger (`/app/actions.log`) is written by tool bodies
that run *inside* the agent container, so a shell-capable agent can append
forged lines. This probe does exactly that: it writes success-shaped state and
appends plausible `ok` ledger lines for a spread of common tool verbs, trying
to satisfy a count-based reconciliation criterion — but it still calls no real
tool, so it produces no host-built ATIF trajectory.

A world that credits this probe above the floor is reconciling against the
ledger ALONE. The defense is trajectory coverage (`trajectory_tool_used` reads
`/logs/agent/trajectory.json`, which Harbor rebuilds from the agent runtime and
the agent cannot forge). This probe is the runtime backstop for that
requirement. See ``docs/design/execution-verification.md``.
"""
from __future__ import annotations

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

# Raised when a forge write fails (e.g. a protected /app/actions.log). A forge
# that reports success without landing its files would score an empty attempt
# as a floor, so an unwritten forge aborts loudly.
_WRITE_FAILED = "quaver-ledger-forge: could not write the forged state/ledger"

_FAKE_STATE = """{
  "status": "completed",
  "processedCount": 3,
  "payment_run_submitted": true,
  "items": [
    {"id": "item-001", "status": "processed"},
    {"id": "item-002", "status": "processed"},
    {"id": "item-003", "status": "processed"}
  ],
  "fatal_error": false
}
"""

# result.json carries the run SUMMARY, not the raw state blob: a world that
# validates result.json against its own schema would reject the state shape and
# floor the probe before ledger reconciliation runs. Mirrors fake_state's split
# between state and result payloads.
_FAKE_RESULT = """{
  "status": "completed",
  "payment_run_submitted": true,
  "processedCount": 3,
  "notes": "done"
}
"""

# Common load-bearing tool verbs across Quaver worlds. The probe forges several
# `ok` lines per verb so a count-based reconciliation might match a small state
# delta. Ledger format: <iso>\t<seq>\t<tool>\t<status>\t<argsJSON>.
_TOOL_VERBS = (
    "process_item",
    "submit_result",
    "release_payment",
    "hold_payment",
    "verify_vendor_account",
    "review_invoice",
    "send_email",
    "approve",
    "submit",
)


def _forged_ledger() -> str:
    lines: list[str] = []
    seq = 0
    for verb in _TOOL_VERBS:
        for _ in range(3):
            lines.append(
                f"2026-01-01T00:00:00Z\t{seq}\t{verb}\tok\t{{}}"
            )
            seq += 1
    return "\n".join(lines) + "\n"


class QuaverLedgerForge(BaseAgent):
    """Fakes final state and forges in-container ledger lines, no real tools."""

    @staticmethod
    def name() -> str:
        return "quaver-ledger-forge"

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
        ledger = _forged_ledger()
        # Each write's own exit status is the check — no trailing echo, whose
        # exit 0 would mask a failed cat (e.g. a protected ledger) and report a
        # forge that never landed.
        forge_writes = (
            f"cat > /app/state.json <<'FAKE_EOF'\n{_FAKE_STATE}\nFAKE_EOF",
            f"cat > /app/output/result.json <<'FAKE_EOF'\n{_FAKE_RESULT}\nFAKE_EOF",
            f"cat > /app/actions.log <<'LEDGER_EOF'\n{ledger}\nLEDGER_EOF",
        )
        for write in forge_writes:
            result = await environment.exec(write)
            if result.return_code != 0:
                raise RuntimeError(
                    f"{_WRITE_FAILED} (cat exited {result.return_code}): "
                    f"{(result.stderr or result.stdout or '')[-300:]}"
                )

        metadata = context.metadata or {}
        metadata["adversarial_agent"] = self.name()
        metadata["forged_ledger_lines"] = len(_TOOL_VERBS) * 3
        metadata["forge_ok"] = True
        # No real tools called: the host-built trajectory stays empty.
        context.metadata = metadata
