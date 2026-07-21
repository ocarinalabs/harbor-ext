# Context — ocarinalabs-harbor-ext

Glossary for the adversarial probe library. Terms only; no implementation
detail. When a term below conflicts with usage in code or a review thread,
this file wins — update it here the moment the meaning sharpens.

## Probe

A `harbor.agents.base.BaseAgent` subclass that plays an adversary against a
benchmark world: it acts only through `environment.exec`, and its job is to
*fail* the world's gate. A benchmark that credits any probe above its
configured floor is not publication-ready.

## Floor

The gate outcome where a probe earns no meaningful credit — every gated
reward key at or below the threshold (default `0.01`). "The gate floors the
probe" (gate acts) and "the probe floors" (probe outcome) are the same event
seen from the two sides. A floor is only evidence of a healthy gate when it is
an **honest floor**: the probe genuinely exercised the weakness and the gate
caught it.

## Vacuous floor

A floor reached for the wrong reason — the probe scored zero because its
payload never engaged the gate under test, not because the gate held. Example:
a probe that encodes one world's winning answer scores zero on a different
world because its forged state fails that world's rubric for shape reasons, so
the run proves nothing about that world's gate. A vacuous floor is a
false negative dressed as a pass, and is the failure finding 4 (harbor-ext #1)
is about.

## Reusable probe vs world-specific probe

- **Reusable probe** — exercises a world-agnostic weakness and floors
  honestly on any conformant world (the Berkeley patterns; the
  execution-faking family `fake_state` / `ledger_forge`). Carries the
  `quaver-` name prefix.
- **World-specific probe** — encodes one world's winning answer, and can only
  floor honestly on that world; on any other world it floors vacuously.
  Carries the `ap-payment-` name prefix (contractor-payment-run family).

The distinction is about honest applicability, not about the *defense* a probe
targets: a probe may target a fully general defense (e.g. magnitude
reconciliation) and still be world-specific, because distinguishing a broken
gate from a working one requires a payload that satisfies *that* world's
rubric — which needs the world's answer key.

## Registration seam

The decision of *which probes count for a given world* is a seam that lives in
the **consumer's probe registry**, not in this library. This package exports
probe adapters and names them by convention (`quaver-` / `ap-payment-`); the
ocarina validation gate (`packages/gate` `PROBES`) is the registry that picks
which import paths run in a world's cascade. Placing the seam in the consumer
keeps world scope where the world is known; a scope attribute carried on the
probe here would be read by no one (the consumer keeps its own explicit list)
and so would be a shallow interface with no locality — deliberately not added.

## Spine

The minimal sequence of *real* tool calls a hybrid probe drives through the
world's actual tool bodies so the host-witnessed trajectory legitimately
contains those tool names. The spine buys **coverage** (tool names present);
it is deliberately far smaller than the state the probe then forges, so
**magnitude reconciliation** is what floors the probe.

## Coverage gate vs reconciliation gate

Two distinct execution-verification checks a world's gate can apply to a
claimed final state:

- **Coverage gate** — every tool the final state implies appears at least once
  in the host-witnessed trajectory.
- **Reconciliation gate** (magnitude) — the trajectory shows at least as many
  calls of each counted tool as the state's delta claims.

A probe that means to isolate the reconciliation gate must first *pass*
coverage (its spine witnesses every disposition it forges); otherwise a
coverage gate floors it first and the reconciliation gate is never tested.

## Disposition

A per-invoice outcome in the AP-payment domain: `released`, `held`, or
`escalated`. A probe "forges a disposition" when its written state/ledger
claims an outcome its spine never actually performed.
