# Project 1 software release-candidate protocol

## Purpose

This gate freezes a verifiable Project 1 software candidate. It is not the
SpinTextureDynamicsBench paper release and it does not change any capability
badge automatically.

The gate answers a narrow question:

> Does this exact source tree have the documented package metadata, license,
> executable tests, Wolfram environment, and registered formal-route evidence
> required for a reproducible software release candidate?

## Frozen content

The candidate manifest binds the following items by relative path, byte count,
and SHA-256:

1. `pyproject.toml`, Python source, Wolfram source and tests;
2. required user, evidence-governance and benchmark documentation;
3. the BSD 3-Clause `LICENSE`;
4. the capability registry and all seven full routes;
5. each route's CAS, independent analytic, executable literature,
   assertion-coverage and cross-engine records;
6. route-level and suite-level machine-audit records;
7. the draft benchmark manifest and all five partition manifests;
8. Python/package/platform metadata and a live WolframKernel version probe;
9. actual stdout/stderr from full `pytest`, Ruff and `pip check` commands;
10. commands needed to reproduce the evidence and verify the candidate.

The source-tree digest is computed over a canonical ordered list of source,
Wolfram and test artifact hashes. The manifest itself has a detached SHA-256.

## Gate semantics

`software_release_candidate_ready=true` requires all mandatory artifacts and
all three verification commands to pass, a valid Wolfram metadata probe, all
seven formal-route evidence bundles to remain eligible, and all claim
boundaries to remain fail-closed.

The following states are disclosed but are not silently converted into software
failures or scientific passes:

- held-out benchmark collection and benchmark freeze;
- optional external domain review;
- named-material symmetry/applicability;
- durable public publication.

Consequently, a ready candidate still records:

```text
public_release_badge_registration_ready = false
paper_benchmark_claim_allowed = false
named_material_prediction_allowed = false
```

The public-release badge may be registered only after the exact candidate is
published through a durable channel and that publication artifact is bound to a
separate release result. The held-out paper benchmark remains an independent
work package.

## Create

```bash
python -m spintexture_agent.cli release-candidate create \
  --out analysis/release_candidates/project1_v0.1.0_rc01 \
  --candidate-id project1_v0.1.0_rc01 \
  --require-ready
```

Creation is atomic and non-overwriting. A failed candidate is retained as an
auditable result unless command setup fails before a manifest can be produced.

## Verify

```bash
python -m spintexture_agent.cli release-candidate verify \
  --candidate analysis/release_candidates/project1_v0.1.0_rc01 \
  --require-ready
```

Verification rechecks manifest integrity, every bound artifact, package and
source-tree metadata, command semantics, capability/evidence paths,
cross-engine eligibility, assertion coverage, machine-audit formal status and
the independent benchmark/review/material disclosures.

## Threats covered

Automated tests require rejection of:

- existing-directory overwrite;
- detached digest or artifact hash drift;
- a re-sealed manifest with a false command status;
- replacement of the license by an unrelated file;
- route-to-route evidence swapping;
- weakened paper-benchmark or publication claim boundaries.

The gate does not establish author identity, repository history, a signed Git
tag, archival DOI, external case independence, or material-level empirical
validity. Those require separate publication, benchmark and review records.
