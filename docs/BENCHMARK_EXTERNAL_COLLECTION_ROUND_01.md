# Benchmark v1 External Collection Round 01

## Purpose

Round 01 turns the existing external-authoring contract into a public,
distribution-ready collection release. It does not create external evidence by
itself. The release contains no real participant identity, invitation, case,
rating, or private gold.

The workflow is:

```text
frozen collection release
-> externally published archive hash
-> genuine invitations in a private working ledger
-> independently authored and custodied sealed returns
-> authoring verification and blind intake
-> pre-unseal system freeze
-> custodian-only materialization
-> registration candidate
-> independent release approval
```

Project 1 developers may operate the collection but may not author cases that
are described as independent.

## Frozen Round-01 Scope

The plan targets:

| Partition | Target | Coverage rule |
| --- | ---: | --- |
| `held_out_supported` | 7 | One independently sourced case for each current `full_derivation` route |
| `readability` | 6 | Two cases for each of three declared non-specialist reader audiences |

The seven supported route families are derived from the frozen capability
registry, not maintained as a second handwritten list. Scaffold and
`review_only` routes are ineligible for held-out correctness claims.

Every task fingerprint already registered in any current benchmark partition is
frozen into the exclusion list. Contributors must also reject semantic
paraphrases that test the same material, texture, drive, geometry, and terminal
result; lexical differences do not establish independence.

Readability coverage includes:

- experimental magnetism researchers without specialist derivation training;
- magnetic-imaging or spintronic-device researchers who consume theory output;
- physics graduate readers outside magnetic-texture theory.

At least two eligible independent raters are required for each readability case
under the separate readability protocol.

## Source Eligibility

An eligible submission must provide:

- primary literature or a genuinely external theoretical contribution;
- a stable, hashed source snapshot;
- a resolving citation or stable locator;
- exact equation, section, or page locators;
- a source not used for Project 1 development;
- a gold scope that is supported by the cited source;
- an independent scientific-relevance review.

Unverifiable or retracted sources are not eligible. Intake acceptance verifies
provenance and scope but does not imply that a source is physically correct.

## Role Separation

The case author, gold custodian, Project 1 developer, intake reviewer, release
manager, and later readability raters have distinct information access.

- The external case author selects the source and creates the public task.
- A different external custodian completes and seals private gold.
- Project 1 developers never receive plaintext held-out gold before evaluation.
- A returned packet is not inserted directly into a real manifest.
- Any developer-authored case is development-exposed, not independent held-out
  evidence.

The typed attestations and hashes make deviations visible. They do not replace
ordinary identity, conflict-of-interest, and research-integrity checks.

## Ledger States

The frozen release ledger has no entries. An operator creates a private working
copy only after contacting real people.

| State | Meaning |
| --- | --- |
| `invited` | Invitation sent; no acceptance decision yet |
| `accepted` | Contributor agreed; no return received yet |
| `declined` | Contributor declined; no packet or case may be attached |
| `returned` | Sealed packet hash and submitted case IDs were recorded |
| `withdrawn` | An invited or accepted participant withdrew |

Only `returned` entries may identify a packet and case IDs. A returned entry
requires a prior acceptance timestamp and a separate custodian identity.

Working ledgers contain personal information and must remain outside the public
repository. `benchmark_collection_working/` is ignored for this reason.

## Deadlines

The immutable plan freezes these Round-01 dates in the Asia/Shanghai offset:

| Event | Deadline |
| --- | --- |
| Invitations open | 2026-08-03 00:00:00 +08:00 |
| Acceptance due | 2026-08-17 23:59:59 +08:00 |
| Sealed submission due | 2026-09-30 23:59:59 +08:00 |
| Custody confirmation due | 2026-10-14 23:59:59 +08:00 |
| Intake review closes | 2026-10-21 23:59:59 +08:00 |

A later schedule requires a new collection ID and release directory; this
release must not be overwritten.

## Generate And Verify

Generate the release once at a new path:

```bash
python -m spintexture_agent.cli benchmark-collection launch \
  --out benchmark_collection_releases/v1/round_01
```

Verify it independently:

```bash
python -m spintexture_agent.cli benchmark-collection verify \
  --release benchmark_collection_releases/v1/round_01 \
  --require-ready
```

The release contains:

```text
round_01/
├── release_payload/
│   ├── authoring_packet/
│   ├── frozen_contract/
│   ├── collection_plan.yaml
│   ├── invitation_return_ledger.yaml
│   ├── OPERATOR_INSTRUCTIONS.md
│   └── CHECKSUMS.sha256
├── spintexture_benchmark_v1_external_collection_round_01.zip
├── release_index.yaml
└── release_index.sha256
```

The ZIP uses sorted entries, fixed timestamps, fixed file modes, and uncompressed
stored bytes. Verification checks every payload hash, archive member, metadata,
and a newly rebuilt archive byte-for-byte.

## Trust Boundary

`release_index.sha256` is a detached local digest. Before invitations are sent,
publish that value through an independent durable channel such as a signed
GitHub release or archival DOI. Otherwise an attacker able to rewrite the
release, index, and digest together can replace all local evidence.

Byte reproducibility proves that a declared archive matches a frozen payload.
It does not prove participant identity, source independence, custody behavior,
or physics correctness. Those claims require the later governance and
scientific validation gates.

## Current State

The repository release is a blank launch artifact only. The real
`held_out_supported` and `readability` manifests remain empty, and no external
performance claim is available.
