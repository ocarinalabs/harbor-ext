# ocarinalabs-harbor-ext

Ocarina Labs' Harbor extension. Adversarial probes for benchmark integrity, packaged for stock `harbor>=0.5.0`.

These probes implement the adversarial archetypes from UC Berkeley's ["How we broke top AI agent benchmarks"](https://rdi.berkeley.edu/) audit — null-agent, output-echoing, judge-injection, and state-tampering — as loadable Harbor agents, plus an execution-faking family (fabricated state, forged ledgers, and a real-work-then-rewrite hybrid) that targets the "wrote the answer, did no work" loophole. A benchmark that credits any of these above-floor is not publication-ready.

Shipped separately from [`ocarinalabs/ocarina`](https://github.com/ocarinalabs/ocarina) so that any Harbor-based benchmark author can attest their world against the same gate.

## Install

```bash
pip install ocarinalabs-harbor-ext
# or
uv add ocarinalabs-harbor-ext
```

## Probes

Each probe is a standalone class extending `harbor.agents.base.BaseAgent`. A world passes the gate when **every** general probe scores at or below the configured floor (typically 0.0).

### General gate probes (`quaver-*`)

The reusable cascade — run these against any Harbor world.

| Probe | Pattern | What it does |
|---|---|---|
| `pattern_1.QuaverPattern1` | Berkeley 1 — isolation | Attempts host-mount escapes, proc-filesystem tricks, rubric exfiltration, suid escalation |
| `pattern_4.QuaverPattern4` | Berkeley 4 — judge injection | Writes judge-prompt-injection payloads into agent-controlled paths |
| `pattern_5.QuaverPattern5` | Berkeley 5 — weak matching | Writes pass-tokens (PASS, SUCCESS, yes, 1, true, OK) to standard output paths |
| `pattern_7.QuaverPattern7` | Berkeley 7 — trusting untrusted | Writes directly to verifier state (reward.txt, reward.json, agent trajectory) |
| `fake_state.QuaverFakeState` | Execution faking | Writes success-shaped structured state with zero tool calls behind it |
| `ledger_forge.QuaverLedgerForge` | Execution faking | Fakes state and forges the in-container `/app/actions.log` ledger, still calling no real tool |
| `state_rewrite.QuaverStateRewrite` | Execution faking (hybrid) | Drives a minimal real tool spine (coverage passes), then rewrites final state and forges a matching ledger |

The stock Harbor `nop` agent covers the null-agent archetype. Use it alongside these for full coverage.

### World-specific probes (`ap-payment-*`)

These encode the winning answer for one world — contractor-payment-run — and exist to prove that world's execution gate holds against an adversary that already knows the answer. Load them by submodule path during hardening; they are not part of the general cascade and will floor harmlessly against any other world.

| Probe | What it does |
|---|---|
| `ap_payment_double_payer.ApPaymentDoublePayer` | Drives real tools but pays one invoice twice; should fail duplicate/idempotency criteria while passing coverage |
| `ap_payment_state_forger.ApPaymentStateForger` | Writes the exact winning state with zero tool calls; should score 0 on every execution-gated criterion |

## Run against a benchmark

```bash
# one probe at a time, via Harbor's import-path mechanism
harbor run /path/to/world \
  --agent-import-path ocarinalabs_harbor_ext.probes.pattern_1:QuaverPattern1

harbor run /path/to/world \
  --agent-import-path ocarinalabs_harbor_ext.probes.pattern_4:QuaverPattern4

harbor run /path/to/world \
  --agent-import-path ocarinalabs_harbor_ext.probes.pattern_5:QuaverPattern5

harbor run /path/to/world \
  --agent-import-path ocarinalabs_harbor_ext.probes.pattern_7:QuaverPattern7

# also the stock null-agent baseline
harbor run /path/to/world --agent nop
```

Or orchestrate the full cascade declaratively via Harbor's `harbor jobs start -c job.yaml`:

```yaml
job_name: quaver-adversarial-gate
n_attempts: 1
orchestrator:
  n_concurrent_trials: 5

environment:
  type: docker

agents:
  - name: probe-nop
    name: nop
  - name: probe-isolation
    import_path: ocarinalabs_harbor_ext.probes.pattern_1:QuaverPattern1
  - name: probe-injection
    import_path: ocarinalabs_harbor_ext.probes.pattern_4:QuaverPattern4
  - name: probe-echo
    import_path: ocarinalabs_harbor_ext.probes.pattern_5:QuaverPattern5
  - name: probe-tamper
    import_path: ocarinalabs_harbor_ext.probes.pattern_7:QuaverPattern7

tasks:
  - path: /path/to/world
```

## What each probe signals when it scores above floor

**Pattern 1 (isolation breach)** — the container boundary between agent and host leaks. An agent can write `/host/...` paths, walk `/proc/1/root`, or escalate suid. A world that credits this probe has lost structural isolation; failures here compromise every other safety claim.

**Pattern 4 (judge injection)** — the rubric's LLM-judge consumes agent-controlled text without structural delimiters. A world that credits this probe is coaching its own grader. Fix: wrap agent bytes in `<agent_output>...</agent_output>` with instructions to ignore directives inside.

**Pattern 5 (weak matching)** — the rubric credits any non-empty output or uses substring matching for output-file checks. A world that credits this probe has a non-discriminating capability signal. Fix: replace substring checks with structural equality or semantic comparison.

**Pattern 7 (verifier tamper)** — the agent can write to `/logs/verifier/reward.txt`, `/logs/agent/trajectory.json`, `/tests/`, or other paths the verifier trusts as canonical. A world that credits this probe has a permission drift. Fix: evaluator-owned paths must be root-owned and agent-read-only.

## Developer quickstart

```bash
git clone https://github.com/ocarinalabs/harbor-ext
cd harbor-ext
uv sync --extra dev
uv run pytest
```

## Related

- [ocarinalabs/quaver](https://github.com/ocarinalabs/quaver) — benchmark world generator that uses these probes as a pre-publication gate
- [harbor-framework/harbor](https://github.com/harbor-framework/harbor) — the runtime these probes plug into
- Berkeley "How we broke top AI agent benchmarks" — the empirical case for each probe

## License

MIT
