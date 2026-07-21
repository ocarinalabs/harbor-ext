"""Quaver random-agent probe — the false-positive control.

Drives the world's REAL tools with arbitrary arguments in a random order and a
random multiplicity — through the world's actual tool bodies, exactly as the
``state_rewrite`` spine does — so the host-built trajectory legitimately
witnesses real tool activity, then writes a well-formed but WRONG final state.
It does legitimate-looking work that does not accomplish the task.

Like the rest of the family, it NEVER writes ``/logs/agent/trajectory.json``:
that artifact is host-built from the runtime and the agent cannot forge it (a
hardened world makes it read-only, so a self-write would throw). Coverage
evidence must come from the real tool calls the host witnesses, not an agent
write to the protected path (see ``CONTEXT.md`` and
``docs/design/execution-verification.md``).

A world that credits this probe above the floor is rewarding *activity* rather
than *outcome*: its rubric passes anything that touches the tools and produces
structurally valid output, instead of reconciling the state delta against the
task. A hardened world floors it — the random state never matches the graded
outcome and the tool counts never reconcile.

Generic by construction: the driver imports ``/app/tools-lib.ts`` and calls
whatever functions it exports, so the probe needs no per-world tool knowledge.
On a world without a tools library the driver is a no-op and the probe still
floors on its wrong state.
"""
from __future__ import annotations

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

# Raised when the wrong-state write fails (e.g. a protected path). If the probe
# reported a floor without landing its state, an empty run would score as a
# floor for the wrong reason (no output) rather than the intended one (valid
# actions, wrong outcome) — a vacuous floor. An unwritten state aborts loudly.
_WRITE_FAILED = "quaver-random-agent: could not write the wrong-outcome state"

# Imports every export of the world's tool library and calls each callable a
# random number of times (0-2) in shuffled order with a grab-bag of arbitrary
# arguments. The tool bodies run for real (writing their own in-container
# ledger); the host builds the trajectory from these calls. The driver writes
# NO trajectory itself — that path is host-owned and read-only on a hardened
# world (mirrors the state_rewrite spine).
_RANDOM_DRIVER_SCRIPT = r"""
import * as tools from "/app/tools-lib.ts";

const grabBag: Record<string, unknown>[] = [
  {},
  { id: "item-000" },
  { invoice_id: "INV-0000" },
  { status: "completed" },
  { reason: "arbitrary" },
  { notes: "random run" },
];
const pick = <T>(xs: readonly T[]): T =>
  xs[Math.floor(Math.random() * xs.length)] as T;
const shuffle = <T>(xs: readonly T[]): T[] =>
  xs
    .map((v) => [Math.random(), v] as const)
    .sort((a, b) => a[0] - b[0])
    .map(([, v]) => v);

const callable = Object.entries(tools).filter(
  ([, v]) => typeof v === "function"
) as [string, (a: unknown) => { isError?: boolean }][];

let performed = 0;
for (const [, fn] of shuffle(callable)) {
  const times = Math.floor(Math.random() * 3);
  for (let i = 0; i < times; i += 1) {
    const args = pick(grabBag);
    try {
      fn(args);
    } catch {
      // An arbitrary-argument call may legitimately throw; that is still
      // random activity, and never writing the trajectory means a throw here
      // cannot leave forged coverage behind.
    }
    performed += 1;
  }
}
console.log(`__RANDOM_OK__ ${performed}`);
"""

# Structurally valid but deliberately WRONG final state: the task is not marked
# complete and the processed count is zero, so state and reconciliation both
# fail on any world that grades the outcome rather than mere activity.
_WRONG_STATE = """{
  "status": "in_progress",
  "processedCount": 0,
  "items": [],
  "note": "arbitrary actions taken; task not completed",
  "fatal_error": false
}
"""


class QuaverRandomAgent(BaseAgent):
    """Takes arbitrary valid tool actions; must not earn reward."""

    @staticmethod
    def name() -> str:
        return "quaver-random-agent"

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
        # The tool driver is best-effort on purpose: a world with no
        # /app/tools-lib.ts still leaves the probe floored on its wrong state,
        # so a failed driver must not abort. Its only job is to make coverage-
        # only rubrics see genuine activity when the tools do exist.
        driver = await environment.exec(
            "cat > /tmp/random-driver.ts <<'RANDOM_EOF'\n"
            f"{_RANDOM_DRIVER_SCRIPT}\n"
            "RANDOM_EOF\n"
            "cd /app && bun run /tmp/random-driver.ts 2>&1 || true"
        )
        # The wrong-outcome state IS the load-bearing evidence, so each write's
        # own exit status is the check — no trailing echo, whose exit 0 would
        # mask a failed cat and report a floor the probe never actually set up.
        state_writes = (
            f"cat > /app/state.json <<'STATE_EOF'\n{_WRONG_STATE}\nSTATE_EOF",
            f"cat > /app/output/result.json <<'STATE_EOF'\n{_WRONG_STATE}\nSTATE_EOF",
        )
        for write in state_writes:
            result = await environment.exec(write)
            if result.return_code != 0:
                raise RuntimeError(
                    f"{_WRITE_FAILED} (cat exited {result.return_code}): "
                    f"{(result.stderr or result.stdout or '')[-300:]}"
                )

        metadata = context.metadata or {}
        metadata["adversarial_agent"] = self.name()
        metadata["driver_ok"] = "__RANDOM_OK__" in (driver.stdout or "")
        context.metadata = metadata
