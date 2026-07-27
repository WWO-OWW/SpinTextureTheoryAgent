# Project 1 publication sidecar

This directory contains release tooling that is intentionally outside the
frozen RC04 Python package. Changing this sidecar must not change the exact
software distribution selected for publication.

Create and verify a handoff:

```bash
python release_tools/project1_publication.py create-handoff
python release_tools/project1_publication.py verify-handoff \
  --handoff analysis/publication_handoffs/project1_v0.1.0_rc04_publication01 \
  --require-ready
```

After a human publishes the exact payload through an immutable channel, fill a
copy of `publication_registration_template.yaml` and run:

```bash
python release_tools/project1_publication.py verify-remote \
  --handoff analysis/publication_handoffs/project1_v0.1.0_rc04_publication01 \
  --record /path/to/completed_publication_record.yaml \
  --out analysis/public_release_verifications/project1_v0.1.0_remote01 \
  --require-pass
```

On a documented transparent network that resolves public hosts through the
RFC 2544 range `198.18.0.0/15`, add `--allow-rfc2544-proxy`. This explicit mode
still requires HTTPS hostname validation, an immutable provider URL, the exact
archive hash, and complete archive-member verification. Other non-public
addresses remain forbidden.

The verifier retrieves the public bytes. A DOI or URL typed into a YAML file is
not accepted as evidence by itself.

Recheck the resulting evidence directory before any registry update:

```bash
python release_tools/project1_publication.py verify-remote-result \
  --result analysis/public_release_verifications/project1_v0.1.0_remote01 \
  --require-eligible
```

After registry registration, create a compact snapshot suitable for the public
Git repository. The snapshot keeps the publication record, handoff binding,
selected transport metadata, verifier implementation, hashes, and claim
boundaries, but deliberately omits the downloaded release archive:

```bash
python release_tools/project1_publication.py create-public-snapshot \
  --result analysis/public_release_verifications/project1_v0.1.0_remote01 \
  --out public_release_evidence/v0.1.0 \
  --snapshot-id project1_v0.1.0_public_evidence01

python release_tools/project1_publication.py verify-public-snapshot \
  --snapshot public_release_evidence/v0.1.0 \
  --require-pass
```

Add `--re-fetch` to the verification command to download the immutable asset
again and check its exact hash and archive-member inventory. This remains a
software-distribution check, not held-out, external-review, or named-material
evidence.
