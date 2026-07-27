# Benchmark v1 External Case Authoring Packet

This packet collects independently sourced `held_out_supported` and `readability` cases. It does
not contain a real benchmark case and must not be registered directly.

## Role separation

1. The case author selects a source not used for Project 1 development, writes only the public
   task brief, records exact source/equation locators, and signs the leakage attestation.
2. The gold custodian is a different person. The custodian receives the private gold material,
   seals it as an encrypted or institutionally access-controlled opaque artifact, records its
   SHA-256, and signs the custody attestation.
3. The Project 1 development team receives the public brief, source snapshot, sealed bytes, and
   metadata. It must not receive the password or plaintext gold before the frozen evaluation.

Typed-name attestations and hashes make the process auditable; they do not cryptographically prove
identity or prove that a person never viewed a file. Disclose any deviation instead of claiming a
blind split.

## Case-author workflow

1. Copy the matching file from `case_author/` into `returned/public_cases/` and replace every
   placeholder. Do not include expected equations, answers, reference solutions, or rubric fields.
2. Put a stable source snapshot in `returned/source_snapshots/`.
3. Copy the matching case-registration template into a working file, fill source citation and exact
   equation/page locators, identity, tool policy, repetition policy, and leakage attestation.
4. Send the private gold template and registration file to the gold custodian without sending any
   Project 1 output or evaluator implementation.

## Gold-custodian workflow

1. Check that the case author and custodian are different participants.
2. Complete the private gold. For readability, also complete the private rubric.
3. Seal each private file into an encrypted or access-controlled opaque artifact under
   `returned/sealed_gold/`. Keep the key outside this packet.
4. Compute SHA-256 for the public brief, source snapshot, and every sealed artifact; enter the
   hashes in the case registration.
5. Confirm `mutable: false`, `seal_state: sealed`, `opened_before_evaluation: false`, an empty
   disclosure log, and all custody attestations.
6. Add the completed case registration under `cases` in `packet_manifest.yaml`, set
   `packet_status: submitted`, and return the whole packet without the decryption key.

## Verification

```bash
python -m spintexture_agent.cli benchmark-authoring verify --packet <returned-packet>
```

The verifier hashes but does not parse sealed artifacts. A passing packet is eligible for an intake
review only; it is not automatically inserted into the held-out manifest and is not a benchmark
pass. Gold may be unsealed only by the declared evaluation custodian after methods and scorer are
frozen.
