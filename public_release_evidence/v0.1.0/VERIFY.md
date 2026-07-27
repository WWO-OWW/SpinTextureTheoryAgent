# Verify the Project 1 v0.1.0 public release

This snapshot binds the immutable publication record, the original
remote-verification metadata, the handoff inventory, and the verifier
implementation. It intentionally does not duplicate the release archive.

Verify the checked-in evidence without network access:

```bash
python release_tools/project1_publication.py verify-public-snapshot \
  --snapshot public_release_evidence/v0.1.0 --require-pass
```

Re-fetch the immutable release asset and verify its exact bytes and
archive members:

```bash
python release_tools/project1_publication.py verify-public-snapshot \
  --snapshot public_release_evidence/v0.1.0 --re-fetch --require-pass
```

Only documented transparent networks that map public HTTPS hosts into
RFC 2544 range 198.18.0.0/15 may add `--allow-rfc2544-proxy`.
TLS hostname validation and exact archive hashing remain mandatory.

Passing this check proves public software-distribution integrity only.
It does not prove held-out benchmark performance, external physics
review, or named-material validity.
