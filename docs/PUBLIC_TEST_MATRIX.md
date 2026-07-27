# Public Test Matrix

## Two Repository Contexts

Project 1 distinguishes the full research working tree from the compact public
`main` snapshot.

The full working tree contains development-exposed benchmark cases, gold
answers, evidence runs, external-model transcripts, figure inputs, and other
research fixtures. The compact public snapshot contains the released software,
immutable public evidence, frozen blank collection release, and operator
workflows, but does not republish every development fixture.

This distinction protects held-out and custody boundaries. Missing fixtures
must not be silently reconstructed from private or future evaluation data.

## Portable Tests

When `benchmark_manifests/v1/manifest.yaml` is absent, pytest recognizes the
compact public context. These source tests remain executable:

- `tests/test_public_release_snapshot.py`
- `tests/test_benchmark_operator.py`
- `tests/test_benchmark_outreach.py`
- `release_tools/tests/test_project1_collection_publication.py`

Other collected tests are reported as skipped with an explicit
`development-only fixtures omitted` reason. A skip is not a pass and is not
CAS, physics, benchmark, external-review, or reproducibility evidence.

Run the compact matrix with:

```bash
python -m pip install . pytest
PYTHONPATH=src python -m pytest -q
```

The public CI also runs the critical public-evidence and installed-CLI checks as
separate named steps.

## Full Development Tests

In the full working tree, the benchmark-manifest sentinel exists and the skip
hook is inactive. Therefore the ordinary command runs the complete suite:

```bash
python -m pytest -q
```

Do not copy private ledgers, sealed returns, future held-out cases, plaintext
gold, or participant data into public `main` to make a development-only test
run. Promote only explicitly public, provenance-reviewed artifacts through the
appropriate release or benchmark-registration gate.
