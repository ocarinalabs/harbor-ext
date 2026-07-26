"""World-specific state forger for contractor-payment-run.

Inspects the rubric-shaped state contract and writes the exact winning
final state files directly — zero world tool calls, no ledger, no ATIF
trajectory. Expect execution-gated credit 0 on all state criteria.
"""
# strip-comments: reviewed
from __future__ import annotations

import json

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from ocarinalabs_harbor_ext.probes._contractor_payment_run import (
    WINNING_RESULT as _WINNING_RESULT,
)
from ocarinalabs_harbor_ext.probes._contractor_payment_run import (
    WINNING_STATE as _WINNING_STATE,
)

# Raised when a forge write fails (e.g. a protected path). Reporting faked_paths
# it never wrote would let the probe score an empty attempt as a floor, so an
# unwritten forge aborts loudly.
_WRITE_FAILED = "ap-payment-state-forger: could not write the forged state"


class ApPaymentStateForger(BaseAgent):
    """Writes contractor-payment-run winning state with zero tool calls."""

    @staticmethod
    def name() -> str:
        return "ap-payment-state-forger"

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
        state_json = json.dumps(_WINNING_STATE, indent=2)
        result_json = json.dumps(_WINNING_RESULT, indent=2)
        await environment.exec("mkdir -p /app/output")
        # Only paths whose write actually landed (exit 0) are reported as faked;
        # a failed cat aborts loudly rather than claiming a fake it never wrote.
        writes = (
            ("/app/state.json", state_json),
            ("/app/output/result.json", result_json),
        )
        faked_paths: list[str] = []
        for path, payload in writes:
            result = await environment.exec(
                f"cat > {path} <<'FORGE_EOF'\n{payload}\nFORGE_EOF"
            )
            if result.return_code != 0:
                raise RuntimeError(
                    f"{_WRITE_FAILED} at {path} (cat exited {result.return_code}): "
                    f"{(result.stderr or result.stdout or '')[-300:]}"
                )
            faked_paths.append(path)
        metadata = context.metadata or {}
        metadata["adversarial_agent"] = self.name()
        metadata["tool_calls"] = 0
        metadata["faked_paths"] = faked_paths
        context.metadata = metadata
