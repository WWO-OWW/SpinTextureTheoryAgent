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

## External benchmark collection Round 01

The benchmark collection is published separately from the software release.
Create and verify its non-overwriting handoff with:

```bash
python release_tools/project1_collection_publication.py create-handoff
python release_tools/project1_collection_publication.py verify-handoff \
  --handoff analysis/collection_publication_handoffs/project1_benchmark_v1_round01_publication01 \
  --require-ready
```

Upload the three exact files under `payload/` to a dedicated, versioned GitHub
release. Never attach them to or recreate `v0.1.0`. Complete a copy of
`collection_publication_registration.yaml`, then retrieve and verify every
remote asset:

```bash
python release_tools/project1_collection_publication.py verify-remote \
  --handoff analysis/collection_publication_handoffs/project1_benchmark_v1_round01_publication01 \
  --record analysis/collection_publication_records/project1_benchmark_v1_round01_github01.yaml \
  --out analysis/collection_public_release_verifications/project1_benchmark_v1_round01_github01 \
  --require-pass

python release_tools/project1_collection_publication.py verify-remote-result \
  --result analysis/collection_public_release_verifications/project1_benchmark_v1_round01_github01 \
  --require-eligible
```

Use `--allow-rfc2544-proxy` only for the documented transparent HTTPS proxy
environment described above. The resulting publication evidence still records
0 participant identities, 0 submitted cases, and 0 human ratings. It permits a
real operator to begin invitations; it is not itself benchmark evidence.
