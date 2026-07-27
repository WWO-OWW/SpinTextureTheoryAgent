# Project 1 distribution bundle and clean-install protocol

## Purpose

This gate turns one verified Project 1 software release candidate into a
non-overwriting, checksum-bound distribution bundle. It tests the installed
product outside the source tree. It does not publish the bundle and does not
change any scientific evidence badge.

## Frozen payload

Each bundle contains:

1. a byte-reconstructable normalized source archive;
2. a Python wheel and standard source distribution built from the bound source;
3. an offline wheelhouse containing the resolved runtime dependencies;
4. the canonical `SpinTextureTheory.wl` library and an AFM-stripe example;
5. a machine-readable dependency inventory and `CHECKSUMS.sha256`;
6. a reproduction guide;
7. SHA-256-bound stdout and stderr for every build and smoke command;
8. a detached digest for the distribution manifest.

The wheel must include the Jinja templates, runtime knowledge base and Wolfram
library. These resources are loaded from the installed package, with a source
fallback only for editable development. The wheel must not contain independent
gold scripts or benchmark result records.

The installed capability registry performs schema and evidence-state
consistency validation without reopening repository-only result paths. Full
cross-engine, literature and review artifact verification remains mandatory in
the source-located release-candidate gate before the wheel is built. An
explicit custom registry continues to use full artifact verification by
default.

## Clean-install gate

Creation uses a fresh virtual environment and installs with:

```text
pip install --no-index --find-links <frozen-wheelhouse> <frozen-project-wheel>
```

No source-tree import path or package index is available to this command. The
installed environment must then pass:

- package import and packaged-resource checks;
- `validate` for `configs/afm_stripe_sot.yaml`;
- `plan` for the same frozen input;
- direct loading of the bundled Wolfram library in `WolframKernel`.

The verifier independently rechecks the release-candidate binding, source
archive reconstruction, all artifact hashes, wheel/sdist metadata and content,
dependency inventory, exact command contracts, output markers and claim
boundaries.

## Commands

After a new release candidate has been created and verified:

```bash
python -m spintexture_agent.cli distribution-bundle create \
  --release-candidate analysis/release_candidates/project1_v0.1.0_rc04 \
  --out analysis/distribution_bundles/project1_v0.1.0_rc04_distribution01 \
  --bundle-id project1_v0.1.0_rc04_distribution01 \
  --require-ready

python -m spintexture_agent.cli distribution-bundle verify \
  --bundle analysis/distribution_bundles/project1_v0.1.0_rc04_distribution01 \
  --require-ready
```

Both creation and verification fail closed. Existing output directories are
never overwritten.

## Claim boundary

`distribution_ready=true` means the exact candidate can be packaged and
installed from its frozen local artifacts. It does not mean:

- the bundle has a durable public URL, repository tag or archival DOI;
- `public_release=passed`;
- held-out benchmark evidence exists;
- external expert review passed;
- any named material has been validated.

Those states remain separate. Public-release evidence may be registered only
after this exact bundle and manifest digest are published through a durable
channel.
