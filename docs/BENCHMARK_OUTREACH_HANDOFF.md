# Round-01 Outreach Handoff

## Scope

The outreach handoff is a public-data-only preparation artifact for an
authorized human operator. It binds no-send role drafts and a checklist to the
verified immutable Round-01 collection release. It does not select recipients,
open a communication channel, send messages, record private identities, or
create benchmark evidence.

The three drafts have separate scopes:

- `case_contributor_invitation.md` describes independent source selection and
  public task-authoring requirements.
- `gold_custodian_invitation.md` describes separate-person custody, sealed gold,
  retained keys, and blind-evaluation boundaries.
- `readability_rater_invitation.md` is later-only. It cannot be used until a
  separate readability study packet and schedule are frozen.

## Create

Create once at a new path:

```bash
python -m spintexture_agent.cli benchmark-outreach-handoff create \
  --out analysis/collection_outreach_handoffs/project1_benchmark_v1_round01_outreach01 \
  --handoff-id project1_benchmark_v1_round01_outreach01 \
  --json
```

Creation requires the verified blank-publication evidence. It copies only the
public publication record, public evidence, frozen collection plan, public
operator instructions, and private-ledger protocol. The copied ledger protocol
contains instructions but no ledger or private data.

## Verify

```bash
python -m spintexture_agent.cli benchmark-outreach-handoff verify \
  --handoff analysis/collection_outreach_handoffs/project1_benchmark_v1_round01_outreach01 \
  --require-ready --json
```

The verifier checks:

- exact artifact membership, SHA-256 values, byte sizes, and detached manifest
  digest;
- the immutable GitHub release page and all three exact asset URLs;
- local archive, release-index, detached-digest, and collection-plan bindings;
- the `2026-08-03` opening, all frozen deadlines, seven supported routes, and
  three readability audiences;
- contributor/custodian separation, source eligibility, custody, and private
  ledger requirements;
- absence of email addresses and participant-ID fields;
- strict false claims for messages, participation, returns, cases, ratings,
  benchmark performance, and external review.

Recomputing a modified file hash and manifest digest is insufficient to pass:
the verifier reconstructs the expected outreach plan from the frozen source
contracts and applies semantic checks to the drafts.

## Human Boundary

Before `2026-08-03T00:00:00+08:00`, the package may be verified and reviewed but
not used to claim a sent invitation. After opening, an authorized human may
adapt a draft in a private communication channel. Recipient details and replies
must never be written back into this handoff.

After a real contributor or custodian event occurs, use the separate two-step
private-ledger workflow. The tool cannot infer that an email, message, or reply
occurred and must not fabricate one. Readability ratings use the separate
frozen readability-study protocol rather than the invitation ledger.
