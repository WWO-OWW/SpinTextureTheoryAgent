# Project 1 claim-evidence matrix

> Generated from `knowledge_base/capabilities.yaml`. Do not edit route rows manually.

Capability registry version: `2.0.0`

| Route | Support / derived knowledge | Evidence badges | Permitted claim | Registered evidence | Missing evidence | Limitations |
| --- | --- | --- | --- | --- | --- | --- |
| `afm_stripe_sot_full` | `full_derivation` / `released` | cas_execution=passed<br>analytic_reproduction=passed<br>literature_reproduction=passed<br>assertion_coverage=passed<br>benchmark=registered<br>cross_engine=passed<br>external_review=pending<br>public_release=passed | Complete executable AFM sigma-model and wall-chain derivation under the registered rigid-wall, force, boundary, and stiffness assumptions. | configs/afm_stripe_sot.yaml<br>benchmark_cases/A4_afm_stripe_sot.yaml<br>machine_audit_specs/core3/A4_afm_stripe_sot.yaml<br>analysis/evidence_runs/core3_latest/A4_afm_stripe_sot_evidence/evidence_result.json<br>evidence_cards/core3/A4_afm_stripe_sot.yaml<br>mathematica/gold/A4_afm_stripe_sot_gold.wl<br>literature_reproduction_records/core3/A4_afm_stripe_sot.yaml<br>knowledge_base/assertion_coverage.yaml<br>analysis/assertion_coverage/literature_02/assertion_coverage.json<br>analysis/cross_engine/core3_latest/A4_afm_stripe_sot/cross_engine_result.json<br>public_release_evidence/v0.1.0/public_release_evidence_record.yaml<br>WL: AFMSigmaEquation<br>WL: DomainWallAnsatz<br>WL: CollectiveMassMatrix<br>WL: CollectiveDampingMatrix<br>WL: GeneralizedForce<br>WL: LinearStabilityMatrix | None declared | Rigid fixed-width walls with pinned internal angles.<br>Nearest-neighbor wall stiffness is phenomenological. |
| `fm_skyrmion_sot_full` | `full_derivation` / `released` | cas_execution=passed<br>analytic_reproduction=passed<br>literature_reproduction=passed<br>assertion_coverage=passed<br>benchmark=registered<br>cross_engine=passed<br>external_review=pending<br>public_release=passed | Complete executable rigid FM-skyrmion Thiele derivation with registered topology, SOT, and boundary conventions. | configs/fm_skyrmion_sot.yaml<br>benchmark_cases/B1_fm_skyrmion_sot.yaml<br>machine_audit_specs/core3/B1_fm_skyrmion_sot.yaml<br>analysis/evidence_runs/core3_latest/B1_fm_skyrmion_sot_evidence/evidence_result.json<br>evidence_cards/core3/B1_fm_skyrmion_sot.yaml<br>mathematica/gold/B1_fm_skyrmion_sot_gold.wl<br>literature_reproduction_records/core3/B1_fm_skyrmion_sot.yaml<br>knowledge_base/assertion_coverage.yaml<br>analysis/assertion_coverage/literature_02/assertion_coverage.json<br>analysis/cross_engine/core3_latest/B1_fm_skyrmion_sot/cross_engine_result.json<br>public_release_evidence/v0.1.0/public_release_evidence_record.yaml<br>WL: TopologicalDensity2D<br>WL: ThieleGyrotropicTensor<br>WL: GeneralizedForce | None declared | Rigid, axisymmetric, fixed-helicity approximation.<br>Low-velocity translational collective-coordinate regime. |
| `afm_skyrmion_sot_full` | `full_derivation` / `released` | cas_execution=passed<br>analytic_reproduction=passed<br>literature_reproduction=passed<br>assertion_coverage=passed<br>benchmark=registered<br>cross_engine=passed<br>external_review=pending<br>public_release=passed | Complete executable compensated-AFM skyrmion inertial derivation with sublattice gyrotropic cancellation under the registered assumptions. | configs/afm_skyrmion_inertia.yaml<br>benchmark_cases/B2_afm_skyrmion_sot.yaml<br>benchmark_cases/E1_afm_skyrmion_not_fm_thiele.yaml<br>benchmark_cases/E4_afm_topology_not_total_magnetization.yaml<br>machine_audit_specs/core3/B2_afm_skyrmion_sot.yaml<br>analysis/evidence_runs/core3_latest/B2_afm_skyrmion_sot_evidence/evidence_result.json<br>evidence_cards/core3/B2_afm_skyrmion_sot.yaml<br>mathematica/gold/B2_afm_skyrmion_sot_gold.wl<br>literature_reproduction_records/core3/B2_afm_skyrmion_sot.yaml<br>knowledge_base/assertion_coverage.yaml<br>analysis/assertion_coverage/literature_02/assertion_coverage.json<br>analysis/cross_engine/core3_latest/B2_afm_skyrmion_sot/cross_engine_result.json<br>public_release_evidence/v0.1.0/public_release_evidence_record.yaml<br>WL: AFMSigmaEquation<br>WL: TopologicalDensity2D<br>WL: CollectiveMassMatrix<br>WL: CollectiveDampingMatrix | None declared | Exact sublattice compensation and rigid fixed-helicity texture.<br>Translational mode only; internal modes are excluded. |
| `afm_skyrmion_sot_scaffold` | `scaffold` / `candidate` | cas_execution=pending<br>analytic_reproduction=missing<br>literature_reproduction=missing<br>assertion_coverage=missing<br>benchmark=missing<br>cross_engine=missing<br>external_review=pending<br>public_release=passed | Candidate AFM-skyrmion model and executable derivation scaffold with an explicit missing-evidence list. | configs/afm_skyrmion_safety_scaffold.yaml<br>public_release_evidence/v0.1.0/public_release_evidence_record.yaml<br>WL: AFMSigmaEquation<br>WL: TopologicalDensity2D | Explicit texture profile and boundary conditions.<br>Explicit SOT force-density convention and polarization.<br>Sublattice sign and compensation conventions. | Produces a derivation scaffold, not a complete collective-coordinate result. |
| `fm_antiskyrmion_sot_full` | `full_derivation` / `released` | cas_execution=passed<br>analytic_reproduction=passed<br>literature_reproduction=passed<br>assertion_coverage=passed<br>benchmark=registered<br>cross_engine=passed<br>external_review=pending<br>public_release=passed | Complete executable elliptic antiskyrmion Thiele derivation for the registered anisotropic-DMI ansatz and axes. | configs/fm_antiskyrmion_sot.yaml<br>benchmark_cases/B4_fm_antiskyrmion_sot.yaml<br>machine_audit_specs/extended/B4_fm_antiskyrmion_sot.yaml<br>analysis/evidence_runs/extended_literature_01/B4_fm_antiskyrmion_sot_evidence/evidence_result.json<br>evidence_cards/extended/B4_fm_antiskyrmion_sot.yaml<br>mathematica/gold/B4_fm_antiskyrmion_sot_gold.wl<br>literature_reproduction_records/extended/B4_fm_antiskyrmion_sot.yaml<br>knowledge_base/assertion_coverage.yaml<br>analysis/assertion_coverage/literature_02/assertion_coverage.json<br>analysis/cross_engine/extended_latest/B4_fm_antiskyrmion_sot/cross_engine_result.json<br>public_release_evidence/v0.1.0/public_release_evidence_record.yaml<br>WL: AnisotropicDMIDensity<br>WL: TopologicalDensity2D<br>WL: ThieleGyrotropicTensor | None declared | Elliptic rigid ansatz and fixed helicity.<br>Material-specific anisotropic DMI tensors still require expert confirmation. |
| `fm_meron_topology_full` | `full_derivation` / `released` | cas_execution=passed<br>analytic_reproduction=passed<br>literature_reproduction=passed<br>assertion_coverage=passed<br>benchmark=registered<br>cross_engine=passed<br>external_review=pending<br>public_release=passed | Boundary-conditioned half-integer meron charge for the registered axisymmetric profile and winding convention. | configs/fm_meron_topology.yaml<br>benchmark_cases/C2_fm_meron_topology.yaml<br>machine_audit_specs/extended/C2_fm_meron_topology.yaml<br>analysis/evidence_runs/extended_literature_01/C2_fm_meron_topology_evidence/evidence_result.json<br>evidence_cards/extended/C2_fm_meron_topology.yaml<br>mathematica/gold/C2_fm_meron_topology_gold.wl<br>literature_reproduction_records/extended/C2_fm_meron_topology.yaml<br>knowledge_base/assertion_coverage.yaml<br>analysis/assertion_coverage/literature_02/assertion_coverage.json<br>analysis/cross_engine/extended_latest/C2_fm_meron_topology/cross_engine_result.json<br>public_release_evidence/v0.1.0/public_release_evidence_record.yaml<br>WL: TopologicalDensity2D | None declared | Axisymmetric isolated meron with prescribed far-field boundary. |
| `fm_bimeron_topology_full` | `full_derivation` / `released` | cas_execution=passed<br>analytic_reproduction=passed<br>literature_reproduction=passed<br>assertion_coverage=passed<br>benchmark=registered<br>cross_engine=passed<br>external_review=pending<br>public_release=passed | Additive bimeron charge for the registered well-separated two-meron construction and pairing rules. | configs/fm_bimeron_topology.yaml<br>benchmark_cases/C3_fm_bimeron_topology.yaml<br>machine_audit_specs/extended/C3_fm_bimeron_topology.yaml<br>analysis/evidence_runs/extended_literature_01/C3_fm_bimeron_topology_evidence/evidence_result.json<br>evidence_cards/extended/C3_fm_bimeron_topology.yaml<br>mathematica/gold/C3_fm_bimeron_topology_gold.wl<br>literature_reproduction_records/extended/C3_fm_bimeron_topology.yaml<br>knowledge_base/assertion_coverage.yaml<br>analysis/assertion_coverage/literature_02/assertion_coverage.json<br>analysis/cross_engine/extended_latest/C3_fm_bimeron_topology/cross_engine_result.json<br>public_release_evidence/v0.1.0/public_release_evidence_record.yaml<br>WL: CompositeMeronTopologicalCharge<br>WL: TopologicalDensity2D | None declared | Well-separated constituent approximation and additive charge construction. |
| `fm_vortex_topology_full` | `full_derivation` / `released` | cas_execution=passed<br>analytic_reproduction=passed<br>literature_reproduction=passed<br>assertion_coverage=passed<br>benchmark=registered<br>cross_engine=passed<br>external_review=pending<br>public_release=passed | Closed-contour vortex winding and its distinction from polarity-dependent full-plane topological charge. | configs/fm_vortex_topology.yaml<br>benchmark_cases/C4_fm_vortex_topology.yaml<br>machine_audit_specs/extended/C4_fm_vortex_topology.yaml<br>analysis/evidence_runs/extended_literature_01/C4_fm_vortex_topology_evidence/evidence_result.json<br>evidence_cards/extended/C4_fm_vortex_topology.yaml<br>mathematica/gold/C4_fm_vortex_topology_gold.wl<br>literature_reproduction_records/extended/C4_fm_vortex_topology.yaml<br>knowledge_base/assertion_coverage.yaml<br>analysis/assertion_coverage/literature_02/assertion_coverage.json<br>analysis/cross_engine/extended_latest/C4_fm_vortex_topology/cross_engine_result.json<br>public_release_evidence/v0.1.0/public_release_evidence_record.yaml<br>WL: WindingNumberFromPhase<br>WL: TopologicalDensity2D | None declared | Boundary winding and polarity are reported separately from full-plane charge. |
| `afm_stripe_unspecified_dmi_review` | `review_only` / `candidate` | cas_execution=pending<br>analytic_reproduction=missing<br>literature_reproduction=missing<br>assertion_coverage=missing<br>benchmark=registered<br>cross_engine=missing<br>external_review=pending<br>public_release=passed | Review-only AFM stripe model-selection guidance and a list of symmetry information needed to choose DMI. | configs/afm_stripe_unspecified_dmi.yaml<br>benchmark_cases/E3_afm_stripe_unspecified_dmi.yaml<br>public_release_evidence/v0.1.0/public_release_evidence_record.yaml<br>WL: AFMSigmaEquation | Crystal or interface symmetry needed to select the DMI invariant.<br>Boundary conditions and an explicit SOT-force convention. | No DMI-dependent formula may be claimed while the symmetry is unspecified. |
| `ferrimagnet_skyrmion_sot_review` | `review_only` / `candidate` | cas_execution=pending<br>analytic_reproduction=missing<br>literature_reproduction=missing<br>assertion_coverage=missing<br>benchmark=registered<br>cross_engine=missing<br>external_review=pending<br>public_release=passed | Review-only identification of a two-sublattice ferrimagnetic route and compensation-dependent checks. | configs/ferrimagnet_skyrmion_sot.yaml<br>benchmark_cases/F1_ferrimagnet_skyrmion_compensation.yaml<br>public_release_evidence/v0.1.0/public_release_evidence_record.yaml | Sublattice-resolved angular momenta, damping, torques, and coupling conventions.<br>A compensation-dependent collective-coordinate derivation. | Current output is model-selection guidance only. |
| `altermagnet_stripe_sot_review` | `review_only` / `candidate` | cas_execution=pending<br>analytic_reproduction=missing<br>literature_reproduction=missing<br>assertion_coverage=missing<br>benchmark=missing<br>cross_engine=missing<br>external_review=pending<br>public_release=passed | Candidate altermagnetic Physics IR, symmetry questions, and tensorial derivation plan for expert review. | configs/altermagnet_stripe_sot_review.yaml<br>public_release_evidence/v0.1.0/public_release_evidence_record.yaml | Magnetic space group and allowed response tensors.<br>Microscopic or symmetry-derived SOT form.<br>Tensorial wall mass, damping, stiffness, and force projections. | Ordinary collinear-AFM scalar coefficients cannot be assumed. |
| `noncollinear_afm_skyrmion_sot_review` | `review_only` / `candidate` | cas_execution=pending<br>analytic_reproduction=missing<br>literature_reproduction=missing<br>assertion_coverage=missing<br>benchmark=missing<br>cross_engine=missing<br>external_review=pending<br>public_release=passed | Candidate multisublattice Physics IR and topology/dynamics review plan for a specified noncollinear AFM. | configs/noncollinear_afm_skyrmion_sot_review.yaml<br>public_release_evidence/v0.1.0/public_release_evidence_record.yaml | Sublattice/order-parameter manifold and symmetry constraints.<br>Multi-order-parameter topology and torque definitions.<br>Executable collective-coordinate derivation. | Current output must stop before a single-vector sigma-model formula. |

## Claim rules

- A benchmark pass is interpreted only within the route's declared support level.
- `candidate`, `scaffold`, and `review_only` outputs cannot be cited as completed derivations.
- Benchmark, external-review, and public-release badges are independent; none is inferred from another.
- The displayed knowledge status is a compatibility summary derived from the badges, not an evidence axis.
- Blocked claims remain blocked even when an LLM assigns high confidence.

## Blocked claims by route

### `afm_stripe_sot_full`

- Material-specific quantitative prediction without fitted parameters.
- Unpinned internal-angle or nonlocal wall-interaction dynamics.

### `fm_skyrmion_sot_full`

- Deformable, high-velocity, or material-unspecified skyrmion dynamics.

### `afm_skyrmion_sot_full`

- Uncompensated, noncollinear, or internal-mode AFM-skyrmion dynamics.

### `afm_skyrmion_sot_scaffold`

- A final inertial equation or topological value before profile, boundary, torque, and sublattice conventions are supplied.

### `fm_antiskyrmion_sot_full`

- Applicability to an arbitrary magnetic point group or unconstrained antiskyrmion deformation.

### `fm_meron_topology_full`

- A universal meron charge without core and far-field boundary data.

### `fm_bimeron_topology_full`

- Exact charge additivity for strongly overlapping cores without direct full-field integration.

### `fm_vortex_topology_full`

- Equating winding number with skyrmion charge without boundary and core information.

### `afm_stripe_unspecified_dmi_review`

- Any DMI-dependent wall equation while the DMI symmetry remains unspecified.

### `ferrimagnet_skyrmion_sot_review`

- A derived ferrimagnetic skyrmion equation or topology based on total magnetization alone.

### `altermagnet_stripe_sot_review`

- Reuse of scalar collinear-AFM mass, damping, stiffness, or SOT coefficients as a final altermagnetic result.

### `noncollinear_afm_skyrmion_sot_review`

- Reduction to a single Neel vector or total-magnetization topology without symmetry proof.
