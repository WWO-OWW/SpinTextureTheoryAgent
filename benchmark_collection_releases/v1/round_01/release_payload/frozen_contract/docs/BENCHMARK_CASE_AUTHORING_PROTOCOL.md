# Benchmark v1 External Case-Authoring Protocol

## Purpose

This protocol collects independently sourced cases for the
`held_out_supported` and `readability` partitions of SpinTextureDynamicsBench
v1. It prevents the current development process from writing new cases and then
calling them held-out.

The authoring packet is an intake mechanism, not a benchmark manifest and not a
score. A verified submission remains outside `benchmark_manifests/v1` until a
separate acceptance, scorer-pilot, and freeze step is completed.

## Information Boundary

Each submission separates three artifact classes:

| Artifact | Visible before evaluation | Purpose |
| --- | --- | --- |
| Public task brief | Yes | Prompt, structured input, target outputs, tools, repetitions, audience |
| Source snapshot | Yes to intake auditor | Citation, provenance, and equation/page locator verification |
| Sealed gold/rubric | No plaintext access | Reference derivation and, for readability, the human-rating rubric |

The verifier parses the public brief and metadata. It only hashes sealed bytes;
it does not decrypt or parse private gold.

## Roles

### Case author

The case author must be independent of Project 1 development. They select a
primary source, write the public task, record exact equation/page locators, and
attest that they did not inspect development cases, agent outputs, gold answers,
or evaluator implementation.

### Gold custodian

The gold custodian must be a different participant and independent of Project 1
development. They freeze the private reference material, retain the decryption
key or access control outside the packet, record hashes and seal time, and
attest that plaintext gold was not disclosed to the development team.

The role split reduces accidental leakage. Typed names and declarations are
auditable records, not cryptographic proof of identity or behavior.

## Generate A Blank Packet

```bash
python -m spintexture_agent.cli benchmark-authoring packet \
  --out benchmark_authoring_packets/v1_template
```

Generation is non-overwriting. A different output path is required for every
new collection round.

The blank packet contains:

```text
packet_manifest.yaml
OPERATOR_GUIDE.md
case_author/
  held_out_supported_public_case_template.yaml
  held_out_supported_registration_template.yaml
  readability_public_case_template.yaml
  readability_registration_template.yaml
gold_custodian/
  gold_answer_template.yaml
  readability_rubric_template.yaml
returned/
  public_cases/
  source_snapshots/
  sealed_gold/
```

No template file is a real benchmark case. The initial manifest has
`packet_status: template` and an empty `cases` list.

## Verify A Returned Packet

```bash
python -m spintexture_agent.cli benchmark-authoring verify \
  --packet /path/to/returned_packet
```

For an automated intake gate:

```bash
python -m spintexture_agent.cli benchmark-authoring verify \
  --packet /path/to/returned_packet \
  --require-ready
```

The verifier rejects:

- duplicate packet IDs or task fingerprints;
- IDs already registered in the benchmark;
- task fingerprints overlapping development-exposed data;
- missing or hash-mismatched public, source, or sealed artifacts;
- public briefs containing expected-answer, gold, solution, or rubric keys;
- source records without citation or equation/page locators;
- a case author and gold custodian who are the same participant;
- participants who are not independent of Project 1 development;
- leakage attestations showing access to development evidence;
- mutable, unsealed, prematurely opened, or disclosed private material;
- incomplete handoff, signatures, or timezone-aware timestamps;
- scorer, tool, or repetition-policy drift between registration and public task.

## What Passing Means

`ready_for_intake=true` means the packet is structurally complete, its declared
information boundary is consistent, and artifact bytes match the recorded
hashes. It does not prove the scientific gold is correct, prove contributor
identity, or make a case held-out by itself.

Before registration, the project still needs to:

1. audit source eligibility and scientific relevance without exposing gold to developers;
2. verify that the scorer can evaluate allowed equivalent formulations;
3. assign a frozen benchmark version and immutable artifact hashes;
4. lock method/tool/repetition policies;
5. transfer the decryption key only to the evaluation custodian after system freeze.

Any early unsealing, development leakage, or tuning against the case permanently
changes its leakage status. Such a case may be retained as development data but
must not be relabeled held-out.

## Submit To The Intake Pipeline

After `benchmark-authoring verify --require-ready` passes, create the separate
non-overwriting intake snapshot and review forms:

```bash
python -m spintexture_agent.cli benchmark-intake stage \
  --packet /path/to/returned_packet \
  --out benchmark_intake/v1/round_01
```

Do not add the returned packet directly to a benchmark partition. Source review,
split/scorer/custody gates, and a blind split-freeze preview are defined in the
[benchmark intake and freeze protocol](BENCHMARK_INTAKE_AND_FREEZE_PROTOCOL.md).
