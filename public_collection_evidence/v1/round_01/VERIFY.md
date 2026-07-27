# Verify Round-01 collection publication

This directory records publication of the blank external-collection launch
packet. It contains no participant identity, submitted case, gold answer, or
human rating.

From a repository checkout, first verify that the publication record is bound
to the exact frozen local assets:

```bash
python release_tools/project1_collection_publication.py verify-record \
  --record public_collection_evidence/v1/round_01/publication_record.yaml \
  --require-valid
```

That offline command deliberately does not claim remote verification or launch
eligibility. To reproduce the public-byte evidence, create a fresh handoff and
retrieve all three assets from GitHub:

```bash
python release_tools/project1_collection_publication.py create-handoff \
  --out /tmp/stta-round01-publication-handoff \
  --handoff-id independent-round01-publication-check

python release_tools/project1_collection_publication.py verify-remote \
  --handoff /tmp/stta-round01-publication-handoff \
  --record public_collection_evidence/v1/round_01/publication_record.yaml \
  --out /tmp/stta-round01-publication-verification \
  --require-pass

python release_tools/project1_collection_publication.py verify-remote-result \
  --result /tmp/stta-round01-publication-verification \
  --require-eligible
```

Only add `--allow-rfc2544-proxy` to `verify-remote` when the documented
transparent HTTPS proxy maps public hosts into `198.18.0.0/15`. TLS hostname
validation and exact hashes remain mandatory.

The collection release is separate from software tag `v0.1.0`. Publication
permits an authorized operator to begin genuine invitations no earlier than
2026-08-03; it is not itself held-out or readability evidence.
