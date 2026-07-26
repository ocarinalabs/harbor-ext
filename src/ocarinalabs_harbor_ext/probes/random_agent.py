"""Ocarina random-agent probe — the false-positive control.

Drives the world's REAL tool bodies with arbitrary arguments in a random order
and multiplicity, exactly as the ``state_rewrite`` spine does, then writes a
well-formed but WRONG final state. It does legitimate-looking work that does not
accomplish the task.

A world that credits this probe above the floor is rewarding *activity* rather
than *outcome*: its rubric passes anything that touches the tools and produces
structurally valid output, instead of reconciling the state delta against the
task.

The driver is generic by construction — it imports ``/app/tools-lib.ts`` and
calls whatever that exports, so the probe needs no per-world tool knowledge. The
wrong-state payload is not: its fields are contractor-payment-run's, so on a
world with a different state schema the probe floors on shape and the
activity-versus-outcome question is never reached.

The real calls are also not host-witnessed (``CONTEXT.md``, "trajectory
reachability"), so against a trajectory-gated world this control floors for want
of a trajectory rather than for its wrong outcome.
"""
# strip-comments: reviewed
from __future__ import annotations

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

# An unwritten state aborts loudly: a floor with no output would be vacuous
# (nothing to grade) rather than the intended one (valid actions, wrong outcome).
_WRITE_FAILED = "ocarina-random-agent: could not write the wrong-outcome state"

# Calls each export of the world's tool library 0-2 times in shuffled order with
# arbitrary arguments. The tool bodies run for real and write their own
# in-container ledger.
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
) as [string, (a: unknown) => unknown][];

// A tool can reject bad args by throwing or by returning `{ isError: true }`,
// and an async body can do either after the await — so callOnce awaits before
// judging, and counts a call only when the body neither threw nor errored. A
// rejected call is not activity and must not count toward coverage.
const callOnce = async (
  fn: (a: unknown) => unknown,
  args: unknown,
): Promise<boolean> => {
  try {
    const result = (await fn(args)) as { isError?: boolean } | undefined;
    return !(result && result.isError === true);
  } catch {
    return false;
  }
};

// Only completed calls count: a rejected call did no work, so counting the
// attempt would let the driver claim activity it never produced.
let completed = 0;
for (const [, fn] of shuffle(callable)) {
  const times = Math.floor(Math.random() * 3);
  for (let i = 0; i < times; i += 1) {
    if (await callOnce(fn, pick(grabBag))) completed += 1;
  }
}
// With a small tools-lib every `times` can roll 0 and the random args may all be
// rejected, leaving no activity at all — then a floor would prove only a no-op,
// not the activity-vs-outcome case. So retry every callable against every
// argument until one completes. A world whose tools reject every arbitrary
// argument admits no completion without task knowledge; report honestly.
if (completed === 0 && callable.length > 0) {
  search: for (const [, fn] of callable) {
    for (const args of grabBag) {
      if (await callOnce(fn, args)) {
        completed += 1;
        break search;
      }
    }
  }
}
console.log(`__RANDOM_OK__ ${completed}`);
"""

# Structurally valid but deliberately WRONG: not complete, nothing processed.
_WRONG_STATE = """{
  "status": "in_progress",
  "processedCount": 0,
  "items": [],
  "note": "arbitrary actions taken; task not completed",
  "fatal_error": false
}
"""

_WRONG_RESULT = """{
  "status": "in_progress",
  "processedCount": 0,
  "notes": "arbitrary actions taken; task not completed"
}
"""


class OcarinaRandomAgent(BaseAgent):
    """Takes arbitrary valid tool actions; must not earn reward."""

    @staticmethod
    def name() -> str:
        return "ocarina-random-agent"

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
        # The driver is best-effort: its exit status is deliberately unchecked,
        # because a world with no /app/tools-lib.ts makes the import throw and the
        # probe still floors on its wrong state. Only its stdout is read, for the
        # activity diagnostic below.
        driver = await environment.exec(
            "cat > /tmp/random-driver.ts <<'RANDOM_EOF' && "
            "cd /app && bun run /tmp/random-driver.ts 2>&1\n"
            f"{_RANDOM_DRIVER_SCRIPT}\n"
            "RANDOM_EOF"
        )
        # result.json goes to both the canonical /app/output/ path and the root,
        # as the sibling probes do, so a world grading the root path is not
        # floored for a missing file instead of grading the wrong outcome.
        state_writes = (
            f"cat > /app/state.json <<'STATE_EOF'\n{_WRONG_STATE}\nSTATE_EOF",
            f"cat > /app/output/result.json <<'RESULT_EOF'\n{_WRONG_RESULT}\nRESULT_EOF",
            f"cat > /app/result.json <<'ROOT_RESULT_EOF'\n{_WRONG_RESULT}\nROOT_RESULT_EOF",
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
