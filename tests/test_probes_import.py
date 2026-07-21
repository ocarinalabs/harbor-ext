"""Probe tests.

Two layers:

- Interface smoke: every probe imports, constructs, extends ``BaseAgent``, and
  exposes a unique, correctly-prefixed slug name.
- Behavior: the execution-faking / tamper probes are exercised through their
  public seam — ``run(instruction, environment, context)`` — against a fake
  environment that records the shell commands each probe issues. A Harbor agent
  acts only by calling ``environment.exec``, so the set of commands it issues
  *is* its observable behavior; the tests assert on that rather than on private
  module constants, so they survive an internal rewrite that preserves what the
  probe actually writes.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest
from harbor.environments.base import ExecResult
from harbor.models.agent.context import AgentContext

from ocarinalabs_harbor_ext.probes import (
    ApPaymentDoublePayer,
    ApPaymentStateForger,
    QuaverFakeState,
    QuaverLedgerForge,
    QuaverPattern1,
    QuaverPattern4,
    QuaverPattern5,
    QuaverPattern7,
    QuaverStateRewrite,
)

# The general, reusable adversarial gate: the Berkeley patterns plus the
# execution-faking family. These carry the `quaver-` name prefix and are the
# probes the ocarina validation gate loads by submodule path.
_GATE_PROBES = [
    QuaverPattern1,
    QuaverPattern4,
    QuaverPattern5,
    QuaverPattern7,
    QuaverFakeState,
    QuaverLedgerForge,
    QuaverStateRewrite,
]
# World-specific probes (contractor-payment-run). Loaded ad hoc by submodule
# path during world hardening, not part of the general cascade; they carry an
# `ap-payment-` name prefix on purpose.
_WORLD_PROBES = [ApPaymentDoublePayer, ApPaymentStateForger]
_ALL_PROBES = _GATE_PROBES + _WORLD_PROBES

# A probe name is a non-empty dash-joined lowercase slug.
_PROBE_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")


@pytest.mark.parametrize("probe_cls", _ALL_PROBES)
def test_probe_has_slug_name(probe_cls):
    name = probe_cls.name()
    assert isinstance(name, str)
    assert _PROBE_NAME_RE.match(name), f"{name!r} is not a valid probe slug"


@pytest.mark.parametrize("probe_cls", _GATE_PROBES)
def test_gate_probe_carries_quaver_prefix(probe_cls):
    assert probe_cls.name().startswith("quaver-")


@pytest.mark.parametrize("probe_cls", _WORLD_PROBES)
def test_world_probe_carries_ap_payment_prefix(probe_cls):
    assert probe_cls.name().startswith("ap-payment-")


@pytest.mark.parametrize("probe_cls", _ALL_PROBES)
def test_probe_constructs_and_reports_version(probe_cls, tmp_path: Path):
    # The load-bearing check is that the harbor BaseAgent constructor accepts
    # `logs_dir=` and the subclass is concrete (no unimplemented abstract
    # method); the version is the shipped release string for this package.
    instance = probe_cls(logs_dir=tmp_path)
    assert instance.version() == "1.0.0"


def test_probe_names_are_unique():
    names = {p.name() for p in _ALL_PROBES}
    assert len(names) == len(_ALL_PROBES)
    assert names == {
        "quaver-pattern-1",
        "quaver-pattern-4",
        "quaver-pattern-5",
        "quaver-pattern-7",
        "quaver-fake-state",
        "quaver-ledger-forge",
        "quaver-state-rewrite",
        "ap-payment-double-payer",
        "ap-payment-state-forger",
    }


def test_probes_extend_base_agent():
    from harbor.agents.base import BaseAgent

    for probe_cls in _ALL_PROBES:
        assert issubclass(probe_cls, BaseAgent), f"{probe_cls.__name__} must extend BaseAgent"


# --- behavior through the public run() seam ---------------------------------


class _RecordingEnv:
    """Fake environment that records every exec command and reports success.

    Probes depend on exactly one method of their environment collaborator —
    ``await environment.exec(cmd)`` returning a result with ``return_code`` and
    ``stdout`` — so this duck-typed double captures behavior at the seam the
    probe actually uses, without standing up a real container.
    """

    def __init__(self) -> None:
        self.commands: list[str] = []

    async def exec(self, command: str, *_args, **_kwargs) -> ExecResult:
        self.commands.append(command)
        return ExecResult(return_code=0, stdout="")


_REDIRECT_RE = re.compile(r"cat\s+>>?\s+(\S+)")


def _redirect_targets(commands: list[str]) -> set[str]:
    """Every path a `cat > path` / `cat >> path` heredoc write targets."""
    return {match.group(1) for cmd in commands for match in _REDIRECT_RE.finditer(cmd)}


def _command_writing(commands: list[str], path: str) -> str | None:
    pattern = re.compile(rf"cat\s+>>?\s+{re.escape(path)}\b")
    return next((cmd for cmd in commands if pattern.search(cmd)), None)


def _ok_ledger_rows(commands: list[str]) -> list[list[str]]:
    """Tab-separated 5-column `ok` ledger records written by any command."""
    rows: list[list[str]] = []
    for cmd in commands:
        for line in cmd.splitlines():
            cols = line.split("\t")
            if len(cols) == 5 and cols[3] == "ok":
                rows.append(cols)
    return rows


async def _run(probe_cls, tmp_path: Path) -> _RecordingEnv:
    env = _RecordingEnv()
    await probe_cls(logs_dir=tmp_path).run("do the task", env, AgentContext())
    return env


async def test_pattern_7_tampers_agent_trajectory_not_the_retired_path(tmp_path: Path):
    env = await _run(QuaverPattern7, tmp_path)
    written = _redirect_targets(env.commands)
    # The ATIF trajectory now lives at /logs/agent/; the pre-1.7 /logs path is
    # retired and must not be targeted, or the probe tests a dead location.
    assert "/logs/agent/trajectory.json" in written
    assert "/logs/trajectory.json" not in written
    # It still attempts its core tamper: the canonical verifier reward file.
    assert "/logs/verifier/reward.json" in written
    trajectory_cmd = _command_writing(env.commands, "/logs/agent/trajectory.json")
    assert trajectory_cmd is not None
    assert "ATIF-v1.7" in trajectory_cmd
    # The tamper must create the target's parent dir first: on an environment
    # where Harbor has not pre-created /logs/agent, a bare `cat >` dies on "no
    # such file" and the probe never tests the isolation boundary it exists for.
    assert re.search(r"mkdir -p .*/logs/agent", trajectory_cmd), (
        "pattern-7 must mkdir the trajectory parent before writing"
    )


async def test_pattern_7_creates_every_tamper_target_parent_dir(tmp_path: Path):
    env = await _run(QuaverPattern7, tmp_path)
    for path in (
        "/logs/verifier/reward.txt",
        "/logs/verifier/reward.json",
        "/logs/agent/trajectory.json",
        "/tests/test.sh",
    ):
        cmd = _command_writing(env.commands, path)
        assert cmd is not None, f"pattern-7 must attempt {path}"
        assert "mkdir -p" in cmd, f"pattern-7 must mkdir the parent of {path}"


async def test_fake_state_writes_success_state_with_no_tool_calls(tmp_path: Path):
    env = await _run(QuaverFakeState, tmp_path)
    written = _redirect_targets(env.commands)
    assert "/app/state.json" in written
    assert "/app/output/result.json" in written
    # No ledger and no trajectory: the whole point is state without execution.
    assert "/app/actions.log" not in written
    assert "/logs/agent/trajectory.json" not in written


async def test_ledger_forge_writes_state_and_a_well_formed_ok_ledger(tmp_path: Path):
    env = await _run(QuaverLedgerForge, tmp_path)
    written = _redirect_targets(env.commands)
    assert "/app/state.json" in written
    assert "/app/actions.log" in written
    rows = _ok_ledger_rows(env.commands)
    assert rows, "ledger-forge must write forged ledger rows"
    for cols in rows:
        assert cols[2], "each ledger row names a tool verb"
        assert cols[3] == "ok"


async def test_state_rewrite_runs_real_spine_then_forges_state_and_ledger(tmp_path: Path):
    env = await _run(QuaverStateRewrite, tmp_path)
    written = _redirect_targets(env.commands)
    # The perfect fake finish: winning state plus an APPENDED forged ledger.
    assert "/app/state.json" in written
    assert "/app/actions.log" in written
    rows = _ok_ledger_rows(env.commands)
    assert rows, "state-rewrite must append forged ok ledger rows"
    assert all(cols[3] == "ok" for cols in rows)
    # It drives the world's REAL tools so the host builds the ATIF trajectory
    # from the runtime.
    issued = "\n".join(env.commands)
    assert "/app/tools-lib.ts" in issued


async def test_state_rewrite_never_writes_the_host_owned_trajectory(tmp_path: Path):
    env = await _run(QuaverStateRewrite, tmp_path)
    issued = "\n".join(env.commands)
    # /logs/agent/trajectory.json is host-built (docs/design/execution-
    # verification.md): the agent cannot forge it, and a correctly hardened
    # world makes it read-only. If the probe wrote it, that write would throw
    # on a hardened world and the spine premise check would abort — so the
    # probe could never reach magnitude reconciliation exactly where it
    # matters. The coverage evidence must come from the real tool calls the
    # host witnesses, never an agent write to the protected path. (Assert on
    # actual write forms, not mere mentions — the source comments name the path
    # to explain why they must not write it.)
    assert "/logs/agent/trajectory.json" not in _redirect_targets(env.commands)
    assert "writeFileSync" not in issued
    assert "ATIF-v1.7" not in issued


# --- finding 1: double-payer must run from /app so world tools resolve -------


async def test_double_payer_runs_its_script_from_app(tmp_path: Path):
    # The world's tools resolve state/ledger paths against the process cwd; a
    # probe that runs its script from anywhere but /app can write the double
    # payment into a throwaway tree and never mutate the world state it means
    # to break. The run must `cd /app` before invoking bun, matching the
    # state-rewrite spine.
    env = await _run(ApPaymentDoublePayer, tmp_path)
    run_cmd = next(
        (cmd for cmd in env.commands if "bun run /tmp/double-payer.ts" in cmd),
        None,
    )
    assert run_cmd is not None, "double-payer must invoke its script"
    assert re.search(r"cd\s+/app\s*&&\s*bun run /tmp/double-payer\.ts", run_cmd), (
        f"double-payer must run from /app, got: {run_cmd!r}"
    )


def _double_payment_invoice_calls(commands: list[str]) -> int:
    """How many times the emitted script releases INV-4498 (the double pay)."""
    script = "\n".join(commands)
    return len(
        re.findall(
            r'\{\s*invoice_id:\s*"INV-4498"\s*\},\s*releasePayment', script
        )
    )


async def test_double_payer_releases_the_retry_invoice_twice(tmp_path: Path):
    env = await _run(ApPaymentDoublePayer, tmp_path)
    assert _double_payment_invoice_calls(env.commands) == 2, (
        "the probe's whole point is paying INV-4498 twice"
    )


class _FailingRunEnv(_RecordingEnv):
    """Records commands but reports a given substring's command as failed."""

    def __init__(self, failing_fragment: str) -> None:
        super().__init__()
        self._failing_fragment = failing_fragment

    async def exec(self, command: str, *_args, **_kwargs) -> ExecResult:
        self.commands.append(command)
        if self._failing_fragment in command:
            return ExecResult(return_code=127, stdout="", stderr="bun: not found")
        return ExecResult(return_code=0, stdout="")


async def test_double_payer_aborts_loudly_when_its_script_fails(tmp_path: Path):
    env = _FailingRunEnv("bun run /tmp/double-payer.ts")
    # If bun can't run (missing, or /app/tools-lib.ts moved), the double
    # payment never happens; completing normally would let the run score a
    # no-op attempt as a floor and mask a broken probe setup. Abort loudly.
    with pytest.raises(RuntimeError, match="refusing to report"):
        await ApPaymentDoublePayer(logs_dir=tmp_path).run(
            "do the task", env, AgentContext()
        )


# --- finding 2: forged result totals must be internally consistent -----------


def _heredoc_body(commands: list[str], path: str) -> str | None:
    """The heredoc payload a `cat > path <<'EOF' ... EOF` command writes."""
    pattern = re.compile(
        rf"cat\s+>>?\s+{re.escape(path)}\s+<<'[A-Z_]+'\n(.*?)\n[A-Z_]+",
        re.DOTALL,
    )
    for cmd in commands:
        match = pattern.search(cmd)
        if match is not None:
            return match.group(1)
    return None


async def test_state_rewrite_forged_state_has_one_authority_check_per_reviewed(
    tmp_path: Path,
):
    env = await _run(QuaverStateRewrite, tmp_path)
    state = json.loads(_heredoc_body(env.commands, "/app/state.json") or "{}")
    reviewed = state["reviewed_invoice_ids"]
    checks = state["authority_checks"]
    # Single-defect: an empty authority_checks against 36 reviewed invoices is
    # a shape inconsistency a rubric can reject before release-magnitude
    # reconciliation. The forged state must supply one check per reviewed id,
    # matching the sibling ap-payment-state-forger's shape.
    assert len(checks) == len(reviewed)
    assert {check["invoice_id"] for check in checks} == set(reviewed)
    required = {
        "bank_change_flag",
        "dual_approval_status",
        "invoice_id",
        "matches_master",
        "verdict",
    }
    for check in checks:
        assert required <= check.keys()


# The contractor-payment-run winning answer, as an independent source of truth
# (the oracle values, not re-derived from probe code): the forge must match it
# so only trajectory-magnitude reconciliation distinguishes the probe.
_REAL_RELEASED = {"INV-4501", "INV-4502", "INV-4503", "INV-4507"}
_REAL_TOTAL_RELEASED = 42650


async def test_state_rewrite_forges_the_real_contractor_answer(tmp_path: Path):
    env = await _run(QuaverStateRewrite, tmp_path)
    state = json.loads(_heredoc_body(env.commands, "/app/state.json") or "{}")
    result = json.loads(
        _heredoc_body(env.commands, "/app/output/result.json") or "{}"
    )
    assert set(state["released_invoice_ids"]) == _REAL_RELEASED
    assert result["total_released_amount"] == _REAL_TOTAL_RELEASED
    records = {rec["invoice_id"]: rec for rec in state["payment_records"]}
    # Concrete remittance data from the oracle, never placeholders.
    assert records["INV-4501"]["vendor_id"] == "VEND-1001"
    assert records["INV-4501"]["amount"] == 8400
    assert records["INV-4501"]["remit_fingerprint"] == "RL-4021-ACH"
    assert all(
        rec["vendor_id"] != "VEND-0000" for rec in state["payment_records"]
    )


async def test_state_rewrite_held_authority_matches_hold_reason(tmp_path: Path):
    env = await _run(QuaverStateRewrite, tmp_path)
    state = json.loads(_heredoc_body(env.commands, "/app/state.json") or "{}")
    checks = {check["invoice_id"]: check for check in state["authority_checks"]}
    # INV-4498 is held because it already settled — not a bank-change hold — so
    # its authority verdict must not claim bank_change_unapproved, which would
    # contradict the hold reason and let shape validation reject the forge.
    assert checks["INV-4498"]["verdict"] == "verified_account_of_record"
    assert checks["INV-4498"]["bank_change_flag"] is False


async def test_both_ap_probes_forge_the_identical_winning_answer(tmp_path: Path):
    # state_rewrite and ap_payment_state_forger must claim the SAME winning
    # answer; their only honest difference is the execution evidence behind it
    # (a real spine + forged ledger vs nothing). Sharing one source of truth is
    # what keeps them from drifting into shape inconsistencies that produce
    # vacuous floors.
    rewrite = await _run(QuaverStateRewrite, tmp_path)
    forger = await _run(ApPaymentStateForger, tmp_path)
    rewrite_state = json.loads(_heredoc_body(rewrite.commands, "/app/state.json") or "{}")
    forger_state = json.loads(_heredoc_body(forger.commands, "/app/state.json") or "{}")
    assert rewrite_state == forger_state
    rewrite_result = json.loads(
        _heredoc_body(rewrite.commands, "/app/output/result.json") or "{}"
    )
    forger_result = json.loads(
        _heredoc_body(forger.commands, "/app/output/result.json") or "{}"
    )
    assert rewrite_result == forger_result


async def test_state_rewrite_forged_result_totals_are_consistent(tmp_path: Path):
    env = await _run(QuaverStateRewrite, tmp_path)
    result_body = _heredoc_body(env.commands, "/app/output/result.json")
    assert result_body is not None, "state-rewrite must forge result.json"
    result = json.loads(result_body)
    state_body = _heredoc_body(env.commands, "/app/state.json")
    assert state_body is not None
    state = json.loads(state_body)
    released_total = sum(
        record["amount"] for record in state["payment_records"]
    )
    # An arithmetic-consistency gate must not be able to reject the probe as
    # malformed before magnitude reconciliation runs: the forged result's
    # released total must equal the sum of its own payment records and match
    # the released count.
    assert result["total_released_amount"] == released_total
    assert result["payment_count"] == len(state["released_invoice_ids"])
    assert released_total > 0, "a zero total is the inconsistency finding 2 flags"


# --- finding 3: the real spine must witness every disposition it forges ------


def _spine_called_verbs(commands: list[str]) -> set[str]:
    script = "\n".join(commands)
    return set(re.findall(r'call\(\s*"([a-z_]+)"', script))


def _forged_ledger_verbs(commands: list[str]) -> set[str]:
    return {cols[2] for cols in _ok_ledger_rows(commands)}


async def test_state_rewrite_spine_witnesses_every_forged_disposition(tmp_path: Path):
    env = await _run(QuaverStateRewrite, tmp_path)
    spine_verbs = _spine_called_verbs(env.commands)
    ledger_verbs = _forged_ledger_verbs(env.commands)
    # Coverage gates check that the host-witnessed trajectory contains every
    # tool the forged state/ledger implies. If the spine never performs a
    # disposition the ledger claims (hold_payment, escalate_invoice), a
    # coverage gate floors the probe before magnitude reconciliation — the
    # weakness it actually targets — is ever exercised.
    missing = ledger_verbs - spine_verbs
    assert not missing, f"spine must witness every forged verb; missing {missing}"
    assert {"hold_payment", "escalate_invoice"} <= spine_verbs


def _spine_call_counts(commands: list[str]) -> Counter[str]:
    script = "\n".join(commands)
    return Counter(re.findall(r'call\(\s*"([a-z_]+)"', script))


def _forged_ledger_counts(commands: list[str]) -> Counter[str]:
    return Counter(cols[2] for cols in _ok_ledger_rows(commands))


async def test_state_rewrite_ledger_plus_spine_reconciles_to_state(tmp_path: Path):
    env = await _run(QuaverStateRewrite, tmp_path)
    state = json.loads(_heredoc_body(env.commands, "/app/state.json") or "{}")
    forged = _forged_ledger_counts(env.commands)
    spine = _spine_call_counts(env.commands)
    # Single-defect invariant: the in-container ledger (the spine's real lines
    # plus the forged remainder) must total the forged state's per-disposition
    # counts exactly. If they disagree, arithmetic ledger-vs-state
    # reconciliation rejects the probe as malformed before the release-
    # magnitude test — the one defect this probe isolates — ever runs.
    for verb, state_key in (
        ("review_invoice", "reviewed_invoice_ids"),
        ("verify_vendor_account", "reviewed_invoice_ids"),
        ("release_payment", "released_invoice_ids"),
        ("hold_payment", "held_invoice_ids"),
        ("escalate_invoice", "escalated_invoice_ids"),
    ):
        assert forged[verb] + spine[verb] == len(state[state_key]), (
            f"{verb}: forged {forged[verb]} + spine {spine[verb]} "
            f"!= state {len(state[state_key])}"
        )


async def test_state_rewrite_spine_performs_the_declared_ids(tmp_path: Path):
    # The forge loops skip the spine-performed ids by value; if the spine
    # script drifts to different ids the ledger reconciliation silently breaks,
    # so pin the spine's release/hold/escalate ids to the module constants.
    from ocarinalabs_harbor_ext.probes import state_rewrite as sr

    env = await _run(QuaverStateRewrite, tmp_path)
    script = "\n".join(env.commands)

    def _called_id(verb: str) -> str | None:
        match = re.search(
            rf'call\(\s*"{verb}",\s*\{{\s*invoice_id:\s*"([A-Z0-9-]+)"', script
        )
        return match.group(1) if match else None

    assert _called_id("release_payment") == sr._SPINE_RELEASED
    assert _called_id("hold_payment") == sr._SPINE_HELD
    assert _called_id("escalate_invoice") == sr._SPINE_ESCALATED


class _FailingSpineEnv(_RecordingEnv):
    """Records commands but reports the spine's bun run as a hard failure."""

    async def exec(self, command: str, *_args, **_kwargs) -> ExecResult:
        self.commands.append(command)
        if "bun run /tmp/rw-spine.ts" in command:
            return ExecResult(
                return_code=1,
                stdout="error: Cannot find module '/app/tools-lib.ts'",
            )
        return ExecResult(return_code=0, stdout="")


async def test_state_rewrite_aborts_loudly_when_spine_fails(tmp_path: Path):
    env = _FailingSpineEnv()
    # A probe that cannot establish its real-tool premise must not proceed to
    # forge: a forged ledger that assumes the spine's release landed would make
    # the probe fail for the wrong reason. It aborts loudly instead.
    with pytest.raises(RuntimeError, match="refusing to forge"):
        await QuaverStateRewrite(logs_dir=tmp_path).run(
            "do the task", env, AgentContext()
        )
    assert not any("/app/state.json" in cmd for cmd in env.commands), (
        "no state must be forged once the spine premise fails"
    )


async def test_state_rewrite_aborts_when_a_forge_write_fails(tmp_path: Path):
    # The spine succeeds, but appending the forged ledger fails. Completing
    # normally would leave partial evidence (state without a matching ledger),
    # which floors the probe for ledger/shape reasons instead of the intended
    # release-magnitude gap — so the forge step must fail loudly like the spine.
    env = _FailingRunEnv("cat >> /app/actions.log")
    with pytest.raises(RuntimeError, match="incomplete forge"):
        await QuaverStateRewrite(logs_dir=tmp_path).run(
            "do the task", env, AgentContext()
        )
