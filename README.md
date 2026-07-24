# ocarinalabs-harbor-ext

Ocarina Labs' Harbor extension. Adversarial probes for benchmark integrity, packaged for stock `harbor>=0.5.0`.

These probes implement the adversarial archetypes from UC Berkeley's ["How we broke top AI agent benchmarks"](https://rdi.berkeley.edu/) audit — isolation escape, judge injection, success-token echo, and verifier tamper — as loadable Harbor agents, plus an execution-faking family (fabricated state, forged ledgers, and a real-work-then-rewrite hybrid) and a set of false-positive controls. A benchmark that credits any general probe above the configured floor is not publication-ready.

Shipped separately from [`ocarinalabs/ocarina`](https://github.com/ocarinalabs/ocarina) so that any Harbor-based benchmark author can attest their world against the same gate.

## Install

```bash
pip install ocarinalabs-harbor-ext
# or
uv add ocarinalabs-harbor-ext
```

## Probes

Each probe is a standalone class extending `harbor.agents.base.BaseAgent`. A world passes the gate when **every** general probe scores at or below the configured floor (typically 0.0).

### General gate probes (`ocarina-*`)

The reusable cascade — run these against any Harbor world.

| Import path | Registered name | What it catches |
|---|---|---|
| `isolation_escape:OcarinaIsolationEscape` | `ocarina-isolation-escape` | Container-isolation breaches — host-mount escapes, `/proc/1/root` walks, rubric exfiltration, suid escalation |
| `judge_injection:OcarinaJudgeInjection` | `ocarina-judge-injection` | LLM-judge criteria that read agent-controlled text without structural isolation (prompt-injection payloads) |
| `success_token_echo:OcarinaSuccessTokenEcho` | `ocarina-success-token-echo` | Rubrics that credit any non-empty reply or substring-match output files (writes `PASS`/`SUCCESS`/`yes`/`1`/`true`/`OK`) |
| `reward_sink:OcarinaRewardSink` | `ocarina-reward-sink` | Verifier-state tamper — direct writes to `/logs/verifier/reward.*`, the agent trajectory, and `/tests/test.sh` |
| `fake_state:OcarinaFakeState` | `ocarina-fake-state` | State graded without execution verification — writes success-shaped structured state with zero tool calls behind it |
| `ledger_forge:OcarinaLedgerForge` | `ocarina-ledger-forge` | Reconciliation against the in-container ledger alone — fakes state and forges `/app/actions.log`, still calling no real tool |
| `state_rewrite:OcarinaStateRewrite`&nbsp;† | `ocarina-state-rewrite` | Magnitude reconciliation gaps — drives a minimal real tool spine (coverage passes), then rewrites final state and forges a matching ledger |
| `random_agent:OcarinaRandomAgent` | `ocarina-random-agent` | Rubrics that reward activity over outcome — drives the world's real tools with arbitrary args, then writes a well-formed but WRONG final state |
| `forbidden_subprocess:OcarinaForbiddenSubprocess` | `ocarina-forbidden-subprocess` | Outcomes reached by bypassing the sanctioned tools — raw interpreters, network/installs, a detached background subprocess; floored by execution verification and safety checks |
| `shortcut_hunter:OcarinaShortcutHunter` | `ocarina-shortcut-hunter` | Reachable answer leaks — greps the checkers/fixtures for expected literals and hardcodes them into output |

All import paths are under the `ocarinalabs_harbor_ext.probes` package (e.g. `ocarinalabs_harbor_ext.probes.isolation_escape:OcarinaIsolationEscape`).

**† `state_rewrite` is world-specific despite its `ocarina-` name.** It encodes the contractor-payment-run winning answer, and a state-rewrite probe can only floor *honestly* on a world whose answer it knows — on any other world it floors vacuously (the forged state fails that world's rubric for shape reasons, proving nothing about that world's magnitude gate). The "which probes count for this world" seam lives on the consumer side (ocarina `packages/gate` `PROBES`), not here. See `CONTEXT.md` ("reusable vs world-specific probe", "vacuous floor", "registration seam").

The stock Harbor `nop` agent covers Berkeley's null-agent archetype. Use it alongside these for full coverage.

### World-specific probes (`ap-payment-*`)

These encode the winning answer for one world — contractor-payment-run — and exist to prove that world's execution gate holds against an adversary that already knows the answer. Load them by submodule path during hardening; they are not part of the general cascade and will floor harmlessly against any other world.

| Import path | Registered name | What it does |
|---|---|---|
| `ap_payment_double_payer:ApPaymentDoublePayer` | `ap-payment-double-payer` | Drives real tools but releases one invoice twice; should fail duplicate/idempotency criteria while passing coverage |
| `ap_payment_state_forger:ApPaymentStateForger` | `ap-payment-state-forger` | Writes the exact winning state with zero tool calls; should score 0 on every execution-gated criterion |

## Run against a benchmark

Harbor loads a probe through the unified `--agent <module:Class>` flag:

```bash
# one probe at a time
harbor run /path/to/world \
  --agent ocarinalabs_harbor_ext.probes.isolation_escape:OcarinaIsolationEscape

harbor run /path/to/world \
  --agent ocarinalabs_harbor_ext.probes.judge_injection:OcarinaJudgeInjection

# the stock null-agent baseline
harbor run /path/to/world --agent nop
```

Run the whole general cascade with a shell loop:

```bash
PROBES=(
  isolation_escape:OcarinaIsolationEscape
  judge_injection:OcarinaJudgeInjection
  success_token_echo:OcarinaSuccessTokenEcho
  reward_sink:OcarinaRewardSink
  fake_state:OcarinaFakeState
  ledger_forge:OcarinaLedgerForge
  random_agent:OcarinaRandomAgent
  forbidden_subprocess:OcarinaForbiddenSubprocess
  shortcut_hunter:OcarinaShortcutHunter
)
for probe in "${PROBES[@]}"; do
  harbor run /path/to/world --agent "ocarinalabs_harbor_ext.probes.${probe}"
done
harbor run /path/to/world --agent nop
```

`state_rewrite` is world-specific (see the † note above) — run it only against the world whose answer it encodes, by its import path, not as part of the general cascade.

## What each probe signals when it scores above floor

**Isolation escape (Berkeley 1)** — the container boundary between agent and host leaks. An agent can write `/host/...` paths, walk `/proc/1/root`, or escalate suid. A world that credits this probe has lost structural isolation; failures here compromise every other safety claim.

**Judge injection (Berkeley 4)** — the rubric's LLM-judge consumes agent-controlled text without structural delimiters. A world that credits this probe is coaching its own grader. Fix: wrap agent bytes in `<agent_output>...</agent_output>` with instructions to ignore directives inside.

**Success-token echo (Berkeley 5)** — the rubric credits any non-empty output or uses substring matching for output-file checks. A world that credits this probe has a non-discriminating capability signal. Fix: replace substring checks with structural equality or semantic comparison.

**Reward sink (Berkeley 7)** — the agent can write to `/logs/verifier/reward.txt`, `/logs/agent/trajectory.json`, `/tests/`, or other paths the verifier trusts as canonical. A world that credits this probe has a permission drift. Fix: evaluator-owned paths must be root-owned and agent-read-only.

**Execution-faking family (`fake_state`, `ledger_forge`, `state_rewrite`)** — the rubric grades final state without verifying the agent did the work. Fix: add `trajectory_tool_used` coverage plus a ledger/trajectory reconciliation criterion (see `docs/design/execution-verification.md` in the ocarina repo).

**False-positive controls (`random_agent`, `forbidden_subprocess`, `shortcut_hunter`)** — these SHOULD floor on a healthy world; if one scores above floor, the world is rewarding activity over outcome, is blind to work done outside the tools, or leaks its answer key to the agent at runtime.

## Developer quickstart

```bash
git clone https://github.com/ocarinalabs/harbor-ext
cd harbor-ext
uv sync --extra dev
uv run pytest
```

## Related

- [ocarinalabs/ocarina](https://github.com/ocarinalabs/ocarina) — benchmark world generator that uses these probes as a pre-publication gate
- [harbor-framework/harbor](https://github.com/harbor-framework/harbor) — the runtime these probes plug into
- Berkeley "How we broke top AI agent benchmarks" — the empirical case for each probe

## License

MIT
