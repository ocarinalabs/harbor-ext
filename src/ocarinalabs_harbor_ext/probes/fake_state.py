"""Quaver execution-faking probe — the "wrote the answer, did no work" agent.

Writes success-shaped final state to the conventional Quaver state/output
paths WITHOUT calling any world tool, so it leaves no tool side-effect ledger
(`/app/actions.log`) and no ATIF trajectory. It is the canonical faker: an
agent that fabricates the end state a grader reads instead of doing the work.

A world that credits this probe above the floor is grading state without
execution verification — its rubric needs `trajectory_tool_used` coverage plus
a ledger/trajectory reconciliation criterion (see
``docs/design/execution-verification.md``). Distinct from pattern_5 (loose
success tokens in flat output files); this one targets structured state/JSON
rubrics specifically.
"""
from __future__ import annotations

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

# Raised when a fake write fails (e.g. a protected path). Reporting a fake it
# never wrote would let the probe score an empty attempt as a floor and mask a
# broken setup, so an unwritten fake aborts loudly.
_WRITE_FAILED = "quaver-fake-state: could not write the fake state"

# A kitchen-sink "success" state: whatever loose field a state rubric happens
# to check, this tries to satisfy it — WITHOUT any tool call behind it.
_FAKE_STATE = """{
  "status": "completed",
  "done": true,
  "success": true,
  "complete": true,
  "processedCount": 99,
  "processed_count": 99,
  "payment_run_submitted": true,
  "submitted": true,
  "items": [
    {"id": "item-001", "status": "processed"},
    {"id": "item-002", "status": "processed"},
    {"id": "item-003", "status": "processed"}
  ],
  "unauthorized_release_count": 0,
  "fatal_error": false
}
"""

_FAKE_RESULT = """{
  "status": "completed",
  "payment_run_submitted": true,
  "processedCount": 99,
  "released": [],
  "held": [],
  "notes": "done"
}
"""

_TARGETS = (
    ("/app/state.json", _FAKE_STATE),
    ("/app/output/result.json", _FAKE_RESULT),
    ("/app/result.json", _FAKE_RESULT),
)


class QuaverFakeState(BaseAgent):
    """Writes plausible final state with zero tool calls behind it."""

    @staticmethod
    def name() -> str:
        return "quaver-fake-state"

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
        # Each write's own exit status is the check — no trailing echo, whose
        # exit 0 would mask a failed cat and report a fake that never landed.
        written: list[str] = []
        for path, payload in _TARGETS:
            result = await environment.exec(
                f"cat > {path} <<'FAKE_EOF'\n{payload}\nFAKE_EOF"
            )
            if result.return_code != 0:
                raise RuntimeError(
                    f"{_WRITE_FAILED} at {path} (cat exited {result.return_code}): "
                    f"{(result.stderr or result.stdout or '')[-300:]}"
                )
            written.append(path)

        metadata = context.metadata or {}
        metadata["adversarial_agent"] = self.name()
        metadata["faked_paths"] = written
        # No tools called on purpose: the ledger and trajectory stay empty.
        metadata["tool_calls"] = 0
        context.metadata = metadata
