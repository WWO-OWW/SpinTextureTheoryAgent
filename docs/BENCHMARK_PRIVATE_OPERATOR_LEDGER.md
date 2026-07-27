# Round-01 Private Operator Ledger

## Purpose

This ledger records only real invitation-state events after the immutable
Round-01 collection release has passed remote publication verification. It is
an append-only private operations record, not benchmark evidence and not a
messaging system.

The repository retains no real identity, invitation, acceptance, return, case,
or rating. The operator keeps the ledger outside Git, or under the ignored
`benchmark_collection_working/` directory.

## Safety Contract

- The publication gate must verify before initialization.
- Initialization creates one blank snapshot with 0 identities, 0 invitations,
  0 submitted cases, and 0 human ratings.
- Invitations cannot predate `2026-08-03T00:00:00+08:00`.
- Events cannot be future-dated or exceed the frozen Round-01 deadlines.
- Every write requires a reviewed dry-run SHA-256 and an explicit real-event
  confirmation.
- Contributor and gold custodian identities must differ.
- Public participant IDs are random pseudonyms; names and contacts remain only
  in the private ledger.
- Returned packet bytes stay under `incoming_returns/` and are bound by SHA-256
  and byte size. Plaintext gold is not stored in the event YAML.
- Snapshots are numbered, non-overwriting, hash chained, permission restricted,
  and replay verified.
- The tool never sends an invitation, acceptance, reminder, or receipt message.

## Verify The Publication Gate

```bash
python -m spintexture_agent.cli benchmark-operator-ledger gate \
  --require-pass --json
```

This command must report zero identities, cases, and ratings. A passing result
permits private-ledger initialization; it does not establish independent
benchmark evidence.

## Initialize In Two Steps

Choose a private path. Prefer encrypted storage outside the repository.

```bash
python -m spintexture_agent.cli benchmark-operator-ledger initialize \
  --out /private/path/round01_operator_ledger \
  --ledger-id round01_private_ledger \
  --operator-id op_REPLACE_WITH_RANDOM_ID \
  --created-at REPLACE_WITH_CURRENT_ISO8601_TIME --json
```

Review the preview, then supply its exact `preview_sha256`:

```bash
python -m spintexture_agent.cli benchmark-operator-ledger initialize \
  --out /private/path/round01_operator_ledger \
  --ledger-id round01_private_ledger \
  --operator-id op_REPLACE_WITH_RANDOM_ID \
  --created-at REPLACE_WITH_SAME_ISO8601_TIME \
  --commit --preview-sha256 REPLACE_WITH_PREVIEW_SHA256 --json
```

Initialization also writes `OPERATOR_CHECKLIST.md`. Stop if its privacy and
identity checks cannot be satisfied.

## Record A Real Event In Two Steps

Copy an appropriate file from `operator_templates/round_01/` to private
storage. The templates are intentionally invalid and set confirmations to
`false`; replace their placeholders only after the corresponding event occurs.

```bash
python -m spintexture_agent.cli benchmark-operator-ledger record \
  --ledger /private/path/round01_operator_ledger \
  --request /private/path/event_request.yaml --json
```

After reviewing the state transition and preview digest:

```bash
python -m spintexture_agent.cli benchmark-operator-ledger record \
  --ledger /private/path/round01_operator_ledger \
  --request /private/path/event_request.yaml \
  --commit --confirm-real-event \
  --preview-sha256 REPLACE_WITH_PREVIEW_SHA256 --json
```

Supported transitions are:

```text
invitation_sent -> invited
invited -> acceptance_received -> accepted
invited -> decline_received -> declined
invited|accepted -> withdrawal_received -> withdrawn
accepted -> sealed_return_received -> returned
```

No terminal state can be silently reopened.

## Verify The Ledger

```bash
python -m spintexture_agent.cli benchmark-operator-ledger verify \
  --ledger /private/path/round01_operator_ledger \
  --require-valid --json
```

Verification checks permissions, exact snapshot membership, detached digests,
the previous-manifest hash chain, deterministic event replay, publication
bindings, packet hashes, counts, and state transitions. A valid ledger proves
internal record integrity only; it does not prove participant independence,
source quality, physical correctness, or benchmark performance.

## Data Handling

Use encrypted storage and encrypted backups, restrict access to the authorized
operator, and keep contact data out of Git, issues, chat transcripts, reports,
and public release assets. Do not publish the ledger. Later intake and
materialization workflows consume only the required sealed hashes and
pseudonymous metadata under their separate approval contracts.
