# Independent evidence governance

## Purpose

Project 1 does not treat scientific maturity as a mandatory sequence from CAS
to expert review, benchmark, and release. Capability registry v2 stores eight
independent evidence axes in a versioned `evidence_status` object. The object is
embedded in Physics IR and the authoritative JSON record, then rendered in the
human report and Wolfram metadata.

## Axis statuses

- `missing`: no qualifying artifact is registered;
- `pending`: the activity is planned or awaiting a decision;
- `registered`: inputs or cases exist, but no passing result is claimed;
- `passed`: a qualifying result artifact is registered;
- `failed`: an executed evidence check failed;
- `not_applicable`: the axis is outside the declared claim scope.

`registered` and `passed` are deliberately different. Existing development
benchmark cases therefore produce `benchmark=registered`, not `benchmarked`.

## Evidence axes

| Axis | Current qualifying artifact |
| --- | --- |
| `cas_execution` | Structured generated-path execution result |
| `analytic_reproduction` | Evidence Card, independent gold script, and dual-path result |
| `literature_reproduction` | Equation-located reproduction record |
| `assertion_coverage` | Route-level resolution and physics-axis coverage result |
| `benchmark` | Frozen benchmark result record; case files alone are only registered |
| `cross_engine` | Hash-verified second-engine result with exact checks and converged independent numerical quadrature |
| `external_review` | Eligible signed review record |
| `public_release` | Release-gate result with reproducibility and provenance artifacts |

## Compatibility status

`knowledge_status` remains available for older consumers, but it is derived and
validated against the badges. For a `full_derivation` route, the compatibility
summary selects `released`, `benchmarked`, `expert_validated`, or
`cas_validated` when the corresponding independent axis passes. Non-full routes
remain `candidate`. Editing the legacy label without changing evidence axes is
rejected by registry validation.

This summary must not be interpreted as an ordering constraint. In particular,
`benchmark=passed` and `public_release=passed` do not require
`external_review=passed` for known-theory evaluation or software release.

## Claim policies

- Known-theory benchmark claims require full support plus passed CAS, analytic,
  assertion, and benchmark axes. External review is independent.
- Software-release evidence requires a passed release gate. External review is
  independent from releasing a correctly scoped software artifact.
- A passing internal release candidate is not itself a public-release artifact.
  `public_release=passed` additionally requires a durably published artifact
  bound to a separate registration result; candidate generation never mutates
  the capability registry.
- Project 1 `v0.1.0` satisfies this software-only release axis through the
  immutable GitHub release and the compact, re-fetchable evidence under
  `public_release_evidence/v0.1.0/`. The badge does not assert held-out
  benchmark success, external review, or named-material validation.
- Novel material-specific physics claims require full support, a
  `novel_material_specific` claim class, passed CAS/analytic/assertion evidence,
  and passed external adjudication. A review-only route remains candidate.

Blocked claims and route limitations always remain in force, regardless of
badge state or LLM confidence.

## Current snapshot

All seven formal routes have passed CAS execution, independent analytic
reproduction, assertion coverage, bounded SymPy/mpmath cross-engine protocols,
and executable literature reproduction. Exact literature claims are separated
as `exact_coefficient`, `exact_normalized`, or `boundary_conditioned_exact`;
`structural_alignment` cannot promote a coefficient claim. Benchmark cases are
registered but the held-out v1.0 benchmark has not passed. External review is
pending. Public software-release evidence is passed for all shipped routes;
the seven full routes derive `released`, while scaffold/review-only routes stay
`candidate` because release evidence does not replace missing physics
evidence. See
[`CORE3_CROSS_ENGINE_PROTOCOL.md`](CORE3_CROSS_ENGINE_PROTOCOL.md) and
[`EXTENDED_CROSS_ENGINE_PROTOCOL.md`](EXTENDED_CROSS_ENGINE_PROTOCOL.md), and
[`EXTENDED_LITERATURE_REPRODUCTION_PROTOCOL.md`](EXTENDED_LITERATURE_REPRODUCTION_PROTOCOL.md).
