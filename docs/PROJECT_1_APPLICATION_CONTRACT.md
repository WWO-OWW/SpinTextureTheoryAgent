# Project 1 unified application contract

## 1. Product definition

SpinTextureTheoryAgent is one scientific agent with one authoritative reasoning
and validation chain. Different users may receive different levels of
explanation, but not different physics, assumptions, or certainty labels.

Its application contract is:

1. supported problem families receive complete, reproducible derivations;
2. unseen materials or textures receive inspectable candidate Physics IR and
   derivation routes;
3. missing symmetry, boundary, topology, or constitutive information is made
   explicit;
4. candidate knowledge becomes formal support only through a controlled,
   auditable promotion process;
5. every result can be rendered formally or accessibly from the same record.

## 2. Unified reasoning flow

```text
prompt or structured task
  -> normalized physical description
  -> capability and evidence lookup
  -> authoritative Physics IR
  -> theory and ansatz selection
  -> Wolfram derivation
  -> physical and symbolic validation
  -> support level plus knowledge status
  -> formal report and accessible explanation from one record
```

There are no separate experimentalist and theorist reasoning engines.

## 3. Result classes

| Result class | Agent behavior | Permitted claim |
| --- | --- | --- |
| Formally supported | Execute the complete validated route and reproduce all artifacts | Complete derivation under declared assumptions |
| Candidate extension | Generate provisional Physics IR, derivation graph, missing evidence, and review questions | Candidate model for expert examination |
| Review only | Identify plausible theory classes but stop before unsupported formulas | Expert modeling required |
| Unsupported | Explain why no reliable route exists and request necessary information | No physics result claimed |

## 4. Knowledge and evidence states

Every new material, texture, drive, ansatz, or theory template first follows a
formal-support path:

```text
candidate
  -> symmetry_checked
  -> cas_validated
```

CAS execution, analytic reproduction, literature reproduction, assertion
coverage, benchmark evaluation, cross-engine checks, external domain review,
and public release are independent evidence fields. A signed expert review is
not a universal prerequisite for benchmarking known-theory routes or releasing
the software. The legacy `knowledge_status` is retained only as a derived
compatibility summary.

Promotion requires evidence; it is never triggered by LLM confidence alone.

Minimum promotion evidence includes:

- source and provenance for material and symmetry information;
- appropriate order parameter and constraints;
- allowed energy and drive terms;
- topology definition and boundary conditions where relevant;
- executable Wolfram derivation and unresolved-expression checks;
- dimensions, limits, signs, and special-case regressions;
- a versioned gold answer and explicit external-review status;
- benchmark cases including at least one negative or ambiguity case.

Novel material-specific claims without adequate symmetry evidence or external
adjudication remain candidate even when the generic continuum algebra passes.

## 5. One record, one layered human report

The authoritative record contains formulas, assumptions, validation evidence,
uncertainty, support level, independent evidence badges, the derived compatibility
status, sources, and artifact hashes.

Project 1 generates one layered human-facing report containing both accessible
and formal sections. This prevents two independently edited reports from
drifting in formulas, assumptions, warnings, or status. The JSON record remains
the authoritative machine-readable source; Wolfram scripts, raw expressions,
execution logs, and validation evidence remain separate reproducibility
artifacts.

The formal section provides the complete derivation specification, code links,
tensors, boundary terms, conventions, and proof obligations.

The accessible rendering provides:

- a physical picture before equations;
- definitions and units for every symbol;
- why the selected model applies;
- a term-by-term interpretation of the final equation;
- which quantities may be measured or estimated;
- assumptions, failure conditions, and required human checks;
- links to the formal derivation and raw record.

The accessible section must pass consistency checks against the authoritative
record. It may simplify language but may not simplify away uncertainty or alter
the equations.

## 6. Candidate Physics IR contract

An unseen problem must return at least:

```yaml
record_id: null
support_level: review_only
knowledge_status: candidate
evidence_status:
  schema_version: 1.0.0
  claim_class: candidate_extension
  cas_execution: {status: missing, artifact_refs: []}
  analytic_reproduction: {status: missing, artifact_refs: []}
  literature_reproduction: {status: missing, artifact_refs: []}
  assertion_coverage: {status: missing, artifact_refs: []}
  benchmark: {status: missing, artifact_refs: []}
  cross_engine: {status: missing, artifact_refs: []}
  external_review: {status: pending, artifact_refs: []}
  public_release: {status: missing, artifact_refs: []}
candidate_physics_ir: {}
analogy_sources: []
assumptions: []
missing_evidence: []
symmetry_questions: []
boundary_questions: []
candidate_derivation_graph: []
executable_substeps: []
blocked_claims: []
promotion_requirements: []
requires_human_review: true
```

If essential order-parameter or symmetry information is absent, the Agent must
ask for it or stop rather than silently borrowing a familiar model.

## 7. Evaluation

Project 1 evaluates three linked capabilities:

1. **Formal correctness:** exactness and reproducibility on supported routes.
2. **Controlled extension:** usefulness, abstention, missing-evidence detection,
   expert correction count, and promotion trace on held-out problems.
3. **Faithful accessibility:** comprehension and terminology improvement without
   loss of formulas, assumptions, warnings, or certainty labels.

Candidate-extension scores are reported separately from full-derivation scores.

## 8. Boundary with Project 2

Project 1 may explain how theoretical terms relate to measurable quantities. It
does not ingest experimental datasets, infer posterior parameters, optimize the
next measurement, or control instruments. Those closed-loop activities belong
to SpinTextureExperimentAgent after Project 1 is completed.
