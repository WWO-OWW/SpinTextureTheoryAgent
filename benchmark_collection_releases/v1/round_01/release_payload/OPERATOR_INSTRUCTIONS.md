# SpinTextureDynamicsBench v1 External Collection Round 01

This is a distribution-only launch packet. It contains no contributor identity, invitation,
submitted case, or private gold. Do not add a case directly to the real benchmark manifests.

## Collection objective

- Collect one independently authored held-out case for each allowed full-derivation route.
- Collect accessible-explanation cases across all audiences frozen in `collection_plan.yaml`.
- Exclude every semantic fingerprint listed in the frozen plan, including paraphrases that test
  the same material-texture-drive-equation combination.

## Role boundary

1. A Project 1 operator may invite and coordinate external participants, but must not author a
   purportedly independent case or inspect plaintext gold.
2. The external case author independently selects an eligible source and completes the public
   brief and provenance record.
3. A different external gold custodian completes and seals private gold. The custodian retains the
   key outside the returned packet.
4. Identities and invitation states belong only in a working copy of the ledger outside this
   immutable launch release. Never overwrite this release.

## Invitation ledger states

- `invited`: invitation sent; no acceptance decision.
- `accepted`: contributor agreed; no packet returned yet.
- `declined`: contributor declined; no case may be attached.
- `returned`: a sealed packet and submitted case IDs are hash-recorded.
- `withdrawn`: a previously invited or accepted participant withdrew.

## Return workflow

1. Give each accepted contributor a fresh copy of `authoring_packet/`.
2. Follow `authoring_packet/OPERATOR_GUIDE.md`; never share development cases, generated answers,
   gold answers, evaluator source, or another contributor's task.
3. Return a signed, sealed packet by the deadlines in `collection_plan.yaml`.
4. Verify it with `benchmark-authoring verify`, then use the separate intake, freeze, custodian
   materialization, and registration-candidate gates.
5. A returned packet does not modify `held_out_supported.yaml` or `readability.yaml`.

## Verify this release

```bash
python -m spintexture_agent.cli benchmark-collection verify --release <release-directory>   --require-ready
```

The verifier checks payload hashes, launch semantics, ZIP metadata, and a deterministic rebuild.
The detached `release_index.sha256` is useful only after its value is published through an
independent channel such as a signed GitHub release or archival DOI. Local hashes alone do not
prove participant independence or authorship.
