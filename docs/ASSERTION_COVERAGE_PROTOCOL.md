# Full-route assertion coverage protocol

This protocol audits the executed Wolfram results of every Project 1
`full_derivation` route. It complements Evidence Cards and machine-physics
audits; it does not replace either one.

## Inputs

- `knowledge_base/assertion_coverage.yaml`: route-level contracts;
- `analysis/evidence_runs/core3_latest`: executed core-three records;
- `analysis/evidence_runs/extended_literature_01`: executed extended-route
  records with source-to-target literature transforms;
- `knowledge_base/capabilities.yaml`: authoritative list of full routes.

The assertion registry must contain exactly the full routes declared by the
capability registry. Each generated `expected_keys` entry must appear exactly
once in one of the three result classes.

## Result classes

- `must_resolve`: a closed result, formula, tensor, equation, or Boolean
  regression. Failure sentinels and unresolved CAS operator heads fail the
  route.
- `symbolic_by_design`: an intentionally held definition or profile integral.
  It must be present and free of fatal sentinels, but `HoldForm[Integrate[...]]`
  is allowed because the integral defines a model coefficient.
- `metadata`: a convention, result note, DMI label, boundary map, or dimension
  contract. It must be present and free of fatal sentinels.

`Derivative[...]` is not globally forbidden. Derivatives in terminal equations
and profile-dependent residuals are valid symbolic expressions. An unevaluated
`Integrate`, `Solve`, `DSolve`, `Reduce`, or similar operator is forbidden only
for keys declared `must_resolve`.

Fatal sentinels include `$Failed`, `$Aborted`, `Failure[...]`, `Missing[...]`,
`Indeterminate`, `ComplexInfinity`, and directed or overflow infinities.

## Physics axes

Each route maps executable Boolean result keys to four axes:

1. `dimension`;
2. `sign`;
3. `boundary`;
4. `limit`.

An axis has one of four statuses:

- `pass`: every registered assertion evaluated to `True`;
- `fail`: a registered assertion evaluated to a non-true value;
- `missing`: the axis applies but no executable assertion is registered;
- `not_applicable`: the registry gives an explicit reason why the axis is
  outside the route's claim scope.

`not_applicable` is not counted as a pass. It is reported separately. A route
with any `missing` axis is `incomplete`; a route with any failed assertion or
resolution contract is `fail`.

## Reproduction

```bash
python -m spintexture_agent.cli assertion-coverage \
  --registry knowledge_base/assertion_coverage.yaml \
  --evidence-runs \
    analysis/evidence_runs/core3_latest \
    analysis/evidence_runs/extended_literature_01 \
  --out analysis/assertion_coverage/literature_02 \
  --require-complete
```

At a release gate, `--require-complete` makes the command exit nonzero for
`incomplete` as well as `fail`.

## Current status

All seven registered `full_derivation` routes currently pass their resolution
contracts and applicable dimension, sign, boundary, and limit axes. The three
topology-only routes declare the dynamical limit axis `not_applicable` with a
route-specific reason; this status is not counted as a pass.

The current source-located run classifies and resolves 204/204 result keys:
180 `must_resolve`, 8 `symbolic_by_design`, and 16 `metadata`. It executes 51
dimension, sign, boundary, or limit assertions without a missing applicable
axis.

The A4 metric and SOT boundary regressions and the C4 vorticity/core-polarity
sign controls execute in both generated and independent gold paths. This is a
coverage statement for registered claim scopes, not evidence that unseen
materials or textures are formally supported.
