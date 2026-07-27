# SpinTextureDynamicsBench v1 Dataset Card

## Status

- Benchmark ID: `spintexture_dynamics_bench`
- Current version: `0.1.0-development`
- Manifest schema: `1.0.0`
- Freeze status: `draft`
- Release ready: **no**

This document describes an evaluation contract under construction. It is not a
claim that a frozen v1 benchmark exists. The current 11 structured cases were
visible during system development and therefore cannot measure held-out
generalization.

## Purpose

SpinTextureDynamicsBench evaluates whether SpinTextureTheoryAgent selects,
derives, checks, and communicates magnetic-texture theory within a declared
capability boundary. The benchmark separates five primary purposes so that a
model-selection safety test is not reported as a complete symbolic derivation,
and a development regression is not reported as held-out evidence.

| Primary partition | Purpose | Current cases | Current status |
| --- | --- | ---: | --- |
| `development_supported` | Regression tests for formally supported routes | 7 | exposed, mutable |
| `held_out_supported` | Independently sourced supported-route generalization | 0 | not populated |
| `negative_ood` | Unsafe request rejection and out-of-domain routing | 3 | exposed, mutable |
| `candidate_extension` | Provisional Physics IR and review-route quality | 1 | exposed, mutable |
| `readability` | Faithful accessible rendering for non-theory readers | 0 | not populated |

Each case belongs to exactly one primary partition. `leakage_status` is recorded
separately because negative, candidate, and readability evaluations may
eventually contain either development-exposed or independently blinded cases.

## Unit Of Data

Each manifest case records:

- a globally unique `case_id` and semantic `task_fingerprint`;
- the structured case artifact and its source provenance;
- one bounded `claim_class`;
- gold visibility and leakage status;
- scorer identity and allowed tools;
- deterministic and stochastic repetition requirements;
- gold mutability and, after freezing, source and gold SHA-256 digests.

The case YAML remains the executable task definition. The manifest is the
evaluation-governance layer: it does not silently alter the Physics IR, Wolfram
script, validator, or scorer.

## Current Data Provenance

All 11 current cases use `internal_development` provenance, public gold, and
`development_exposed` leakage status. Seven supported cases link separate gold
answer files. Three negative/OOD cases and one candidate case currently use
their rule specification as the mutable expected-behavior artifact. These are
appropriate for regression testing, not independent performance claims.

No current case may be relabeled held-out. A held-out case must be independently
sourced, use blinded gold, have no development task-fingerprint overlap, and be
frozen before scoring a release candidate.

External cases are collected through the
[benchmark case-authoring protocol](BENCHMARK_CASE_AUTHORING_PROTOCOL.md). Its
packet separates public briefs from sealed gold, records author/custodian roles,
and verifies hashes and leakage attestations before intake. Packet verification
does not automatically register a case.

The public [Round-01 collection protocol](BENCHMARK_EXTERNAL_COLLECTION_ROUND_01.md)
freezes target quotas, eligible full-derivation route families, registered
semantic-fingerprint exclusions, source and role criteria, readability audience
coverage, deadlines, and an empty invitation/return ledger. Its deterministic
archive is byte-reconstructable, but it currently records 0 identities, 0
invitations, and 0 returned cases.

Verified returns pass through the separate
[intake and freeze protocol](BENCHMARK_INTAKE_AND_FREEZE_PROTOCOL.md). It creates
a non-overwriting packet snapshot, locks the benchmark/scorer/tool/repetition
contract by hash, records independent source-eligibility decisions, and can
produce preview-only partition entries. A preview never edits the real manifest
and is not executable held-out gold.

After the system is frozen, accepted cases follow the
[custodian materialization and registration protocol](BENCHMARK_MATERIALIZATION_AND_REGISTRATION_PROTOCOL.md).
It freezes the exact system/scorer/split contract, records a one-time custodian
unseal in an isolated evaluation workspace, validates scorer-supported
equivalent forms, and emits a non-registering candidate with checksums. It does
not expose real gold to developers or automatically merge manifests.

## Scoring And Tools

The registered scorer is `structured_rule_scorer_v1`. Current cases permit the
Python orchestrator and local Wolfram kernel. A valid comparison must preserve
the per-case tool policy across compared methods or explicitly report a
different evaluation track.

Deterministic systems require one run. Stochastic systems require three runs
with aggregate statistics and uncertainty rather than cherry-picked outputs.
The current rule evaluator is deterministic; the stochastic policy is recorded
for future external-model comparisons.

## Integrity Checks

The typed manifest loader rejects:

- missing or extra primary partition definitions;
- duplicate case IDs or case artifacts registered in multiple partitions;
- development/held-out task-fingerprint overlap;
- missing case, source, or gold locators;
- claim classes inconsistent with the primary partition;
- unregistered scorers and malformed held-out provenance;
- mutable or unhashed gold in frozen partitions;
- hash drift after a partition is frozen;
- structured case files that are not registered by the suite.

Inspect the current contract with:

```bash
python -m spintexture_agent.cli benchmark-manifest
python -m spintexture_agent.cli benchmark-manifest --json
```

The release gate is intentionally fail-closed:

```bash
python -m spintexture_agent.cli benchmark-manifest --require-release-ready
```

It cannot pass until the suite and every partition are frozen and all five
partitions are nonempty.

## Planned Population And Freeze

1. Publish the Round-01 release-index digest independently and invite genuine external contributors.
2. Obtain source-located cases that were not used to design templates or checks.
3. Assign public task artifacts and blinded gold to separate custodial roles.
4. Check semantic fingerprint overlap before any model run.
5. Stage only packets that pass authoring verification; complete independent source and custody review.
6. Pilot scorers on development cases only; do not tune against held-out gold.
7. Freeze source and sealed-gold artifacts, split, scorer, tools, and repetitions with SHA-256 digests.
8. Materialize private scorer gold through a custodian-only process after system freeze.
9. Run all methods under the registered tool and repetition policy.
10. Publish aggregate and case-level results, failures, exclusions, and confidence intervals.

Readability cases additionally require a predefined rubric and independent
raters. They must test preservation of formulas, assumptions, warnings,
validity limits, and certainty, not merely writing style.

The frozen [readability v1 protocol](READABILITY_EVALUATION_PROTOCOL.md)
requires two eligible independent blinded raters, separates missing,
incomplete, disagreement, pass, and fail states, and prevents clarity scores
from compensating for critical physics omissions. The repository currently
contains no human ratings.

## Known Limitations

- There is currently no held-out supported-route evidence.
- There is currently no human-rated readability evidence.
- The Round-01 collection release exists, but no genuine invitation or return is recorded.
- There is currently no genuine external intake stage or materialized private scorer gold.
- There is currently no real system-freeze package, custodian handoff, or registration candidate.
- The 11 development cases are small and concentrated in existing capability routes.
- Passing structured rules does not by itself establish symbolic or physical correctness.
- External-review, cross-engine, literature-reproduction, benchmark, and public-release
  evidence remain independent badges.

Accordingly, current scores may support software-regression statements only.
They must not be described as benchmark v1 generalization accuracy or as proof
that the agent can solve arbitrary magnetic-texture problems.
