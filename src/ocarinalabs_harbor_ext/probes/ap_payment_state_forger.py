"""World-specific state forger for contractor-payment-run.

Inspects the rubric-shaped state contract and writes the exact winning
final state files directly — zero world tool calls, no ledger, no ATIF
trajectory. Expect execution-gated credit 0 on all state criteria.
"""
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
        await environment.exec(
            f"cat > /app/state.json <<'FORGE_EOF'\n{state_json}\nFORGE_EOF"
        )
        await environment.exec(
            f"cat > /app/output/result.json <<'FORGE_EOF'\n{result_json}\nFORGE_EOF"
        )
        metadata = context.metadata or {}
        metadata["adversarial_agent"] = self.name()
        metadata["tool_calls"] = 0
        metadata["faked_paths"] = ["/app/state.json", "/app/output/result.json"]
        context.metadata = metadata
