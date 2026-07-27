from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .ir import build_physics_ir
from .kb import KnowledgeBase
from .schema import PhysicsIR, TheoryTask
from .selector import SelectedTemplate


@dataclass
class ValidationItem:
    id: str
    status: str
    severity: str
    message: str
    evidence: str = ""
    recommendation: str = ""


@dataclass
class CheckReport:
    items: list[ValidationItem] = field(default_factory=list)

    @property
    def checks(self) -> list[str]:
        return [
            item.message
            for item in self.items
            if item.severity in {"info", "review"} and item.status != "fail"
        ]

    @property
    def warnings(self) -> list[str]:
        return [
            item.message
            for item in self.items
            if item.severity in {"warning", "error"} or item.status == "fail"
        ]

    @property
    def ok(self) -> bool:
        return not any(item.severity == "error" or item.status == "fail" for item in self.items)

    def add(
        self,
        *,
        id: str,
        status: str,
        severity: str,
        message: str,
        evidence: str = "",
        recommendation: str = "",
    ) -> None:
        self.items.append(
            ValidationItem(
                id=id,
                status=status,
                severity=severity,
                message=message,
                evidence=evidence,
                recommendation=recommendation,
            )
        )

    def to_record(self) -> list[dict[str, str]]:
        return [asdict(item) for item in self.items]


def check_task(
    task: TheoryTask,
    template: SelectedTemplate,
    kb: KnowledgeBase,
    physics_ir: PhysicsIR | None = None,
) -> CheckReport:
    report = CheckReport()
    physics_ir = physics_ir or build_physics_ir(task, template, kb)
    texture = kb.texture(task.texture)

    if physics_ir.support_level == "full_derivation":
        report.add(
            id="support_level",
            status="pass",
            severity="info",
            message="Support level: full symbolic derivation.",
            evidence=physics_ir.support_level,
        )
    elif physics_ir.support_level == "scaffold":
        report.add(
            id="support_level",
            status="review",
            severity="review",
            message="Support level: symbolic scaffold with one or more non-derived terminal results.",
            evidence=physics_ir.support_level,
            recommendation="Do not treat terminal collective equations as independently derived yet.",
        )
    else:
        report.add(
            id="support_level",
            status="review",
            severity="warning" if physics_ir.support_level == "unsupported" else "review",
            message=f"Support level: {physics_ir.support_level}.",
            evidence=physics_ir.support_level,
            recommendation="Require expert review before using this task's physical conclusions.",
        )

    if physics_ir.dimension_contract is not None:
        report.add(
            id="dimension_contract",
            status="pass",
            severity="info",
            message="A dimensional convention is declared for executable consistency checks.",
            evidence=physics_ir.dimension_contract.convention,
        )
    elif physics_ir.support_level == "full_derivation":
        report.add(
            id="dimension_contract",
            status="review",
            severity="review",
            message="No executable dimensional convention is declared for this full derivation.",
            recommendation="Declare parameter dimensions and expected terminal-equation dimensions.",
        )

    for index, constraint in enumerate(physics_ir.order_parameter.constraints, start=1):
        report.add(
            id=f"constraint_{index}",
            status="review",
            severity="info",
            message=f"Order-parameter constraint to verify: {constraint}",
            evidence=constraint,
            recommendation="Confirm the generated ansatz satisfies this constraint.",
        )

    if task.material == "collinear_antiferromagnet" and physics_ir.dynamics.type != "sigma_model":
        report.add(
            id="afm_dynamics_type",
            status="fail",
            severity="error",
            message="Collinear AFM should use sigma_model dynamics in the current theory scope.",
            evidence=physics_ir.dynamics.type,
            recommendation="Select an AFM sigma-model template instead of an FM Thiele template.",
        )
    else:
        report.add(
            id="dynamics_type",
            status="pass",
            severity="info",
            message=f"Dynamics class selected: {physics_ir.dynamics.type}",
            evidence=physics_ir.dynamics.expected_equation_type,
        )

    if task.texture in {"skyrmion", "meron", "bimeron", "antiskyrmion"}:
        topology_label = physics_ir.order_parameter.topology_field
        if task.material == "collinear_antiferromagnet":
            topology_label = f"{topology_label} (Neel order parameter)"
        report.add(
            id="topology_field",
            status="review",
            severity="info",
            message=(
                "Topology check required: compute Q from "
                f"{topology_label}."
            ),
            evidence=f"texture topology={texture.get('topology')}",
            recommendation="Do not use total magnetization blindly for AFM or multi-sublattice systems.",
        )

    if task.material == "ferromagnet" and task.texture == "bimeron":
        report.add(
            id="bimeron_pair_conventions",
            status="review",
            severity="review",
            message="Check core polarity and winding conventions for both constituents.",
            evidence="Q_i = p_i w_i / 2",
            recommendation="Verify the signs against the full magnetization field.",
        )
        report.add(
            id="bimeron_overlap_validity",
            status="review",
            severity="review",
            message="The additive constituent-charge model assumes an inspectable meron pair.",
            evidence="well_separated_meron_pair",
            recommendation=(
                "Use direct full-field integration when the constituent cores strongly overlap."
            ),
        )

    if task.drive == "spin_orbit_torque" and task.material == "collinear_antiferromagnet":
        explicit_afm_force = next(
            (
                assumption
                for assumption in (
                    "sot_force_density_explicit",
                    "explicit_sigma_model_force_density",
                )
                if assumption in task.assumptions
            ),
            None,
        )
        if explicit_afm_force:
            report.add(
                id="afm_sot_channel",
                status="pass",
                severity="info",
                message="AFM SOT force density is explicitly declared for symbolic projection.",
                evidence=explicit_afm_force,
            )
        else:
            report.add(
                id="afm_sot_channel",
                status="review",
                severity="review",
                message="Distinguish uniform SOT from staggered SOT in assumptions.",
                evidence="drive=spin_orbit_torque, material=collinear_antiferromagnet",
                recommendation=(
                    "Record whether the torque couples uniformly or as a staggered effective field."
                ),
            )

    if task.drive == "spin_orbit_torque":
        if "symbolic_spin_polarization" in task.assumptions:
            report.add(
                id="sot_polarization",
                status="pass",
                severity="info",
                message="SOT polarization is retained symbolically as {px, py, pz}.",
                evidence="symbolic_spin_polarization",
            )
        elif "in_plane_spin_polarization" in task.assumptions:
            report.add(
                id="sot_polarization",
                status="pass",
                severity="info",
                message="SOT polarization is explicitly restricted to the film plane.",
                evidence="in_plane_spin_polarization",
            )
        else:
            report.add(
                id="sot_polarization",
                status="review",
                severity="review",
                message="SOT polarization and damping-like/field-like decomposition require review.",
                evidence="drive=spin_orbit_torque",
                recommendation=(
                    "Record the spin-polarization direction and separate damping-like and "
                    "field-like torque channels before finalizing forces."
                ),
            )

    if task.material == "ferromagnet" and task.drive == "spin_orbit_torque":
        if "explicit_llg_sot_torque" in task.assumptions:
            report.add(
                id="fm_sot_projection_convention",
                status="pass",
                severity="info",
                message="FM SOT is projected with the declared LLG torque convention.",
                evidence="torque . (m cross partial_q m)",
            )
        else:
            report.add(
                id="fm_sot_projection_convention",
                status="review",
                severity="review",
                message="The FM LLG torque projection convention is not explicit.",
                recommendation="Declare the torque sign and projection inner product.",
            )

    if task.material == "altermagnet":
        report.add(
            id="altermagnet_symmetry_tensor",
            status="review",
            severity="review",
            message="Altermagnet response requires crystal-symmetry-dependent tensors.",
            evidence=physics_ir.dynamics.type,
            recommendation=(
                "Specify the magnetic point group and allowed anisotropic response tensor "
                "before accepting the reduced equation."
            ),
        )
        if task.drive == "spin_orbit_torque":
            report.add(
                id="altermagnet_sot_tensor",
                status="review",
                severity="review",
                message="Altermagnetic SOT form cannot be copied from an isotropic AFM template.",
                evidence="drive=spin_orbit_torque, material=altermagnet",
                recommendation=(
                    "Derive the damping-like and field-like torque tensor from the crystal "
                    "symmetry and current direction."
                ),
            )
        if task.texture == "stripe_domain":
            report.add(
                id="anisotropic_wall_chain_review",
                status="review",
                severity="review",
                message="Stripe wall-chain coefficients may be tensorial in an altermagnet.",
                evidence=physics_ir.dynamics.expected_equation_type,
                recommendation=(
                    "Review whether mass, damping, stiffness, and drive depend on Neel-vector "
                    "orientation, wall angle, and current direction."
                ),
            )

    if task.material == "noncollinear_antiferromagnet":
        report.add(
            id="noncollinear_order_parameter_review",
            status="review",
            severity="review",
            message="Noncollinear AFM requires a multi-order-parameter or SO(3) description.",
            evidence=", ".join(physics_ir.order_parameter.auxiliary),
            recommendation=(
                "Do not collapse the state to a single Neel vector unless symmetry reduction "
                "has been explicitly justified."
            ),
        )
        report.add(
            id="multisublattice_dynamics_review",
            status="review",
            severity="review",
            message="Dynamics should be derived from multi-sublattice LLG or an SO(3) order parameter.",
            evidence=physics_ir.dynamics.type,
            recommendation="Check sublattice torques, constraints, and collective coordinates separately.",
        )
        if task.texture in {"skyrmion", "meron", "bimeron", "antiskyrmion"}:
            report.add(
                id="sublattice_topology_review",
                status="review",
                severity="review",
                message="Topology should be sublattice- or order-parameter-resolved.",
                evidence=str(physics_ir.order_parameter.topology_field),
                recommendation=(
                    "Report which sublattice or composite order parameter carries the topological "
                    "charge instead of using total magnetization blindly."
                ),
            )

    if "dmi_unspecified" in physics_ir.energy_terms:
        report.add(
            id="dmi_symmetry",
            status="review",
            severity="warning",
            message="DMI term is present but its symmetry class is unspecified.",
            evidence=", ".join(physics_ir.energy_terms),
            recommendation="Choose interfacial_dmi, bulk_dmi, or anisotropic_dmi explicitly.",
        )
    elif "interfacial_dmi" in physics_ir.energy_terms:
        report.add(
            id="dmi_symmetry",
            status="pass",
            severity="info",
            message="DMI symmetry selected: interfacial_dmi.",
            evidence=str(task.geometry),
        )
    elif "anisotropic_dmi" in physics_ir.energy_terms:
        report.add(
            id="dmi_symmetry",
            status="pass",
            severity="info",
            message="DMI symmetry selected: anisotropic_dmi.",
            evidence=str(task.geometry),
        )

    if task.material == "collinear_antiferromagnet" and task.texture == "stripe_domain":
        if "localized_wall_boundary_terms_vanish" in task.assumptions:
            report.add(
                id="collective_boundary_terms",
                status="pass",
                severity="info",
                message="Localized-wall boundary terms are explicitly assumed to vanish.",
                evidence="localized_wall_boundary_terms_vanish",
            )
        else:
            report.add(
                id="collective_boundary_terms",
                status="review",
                severity="review",
                message="Check boundary terms in the collective-coordinate projection.",
                evidence=physics_ir.dynamics.expected_equation_type,
                recommendation=(
                    "Verify which spatial boundary terms are dropped when projecting the AFM "
                    "sigma model onto stripe wall-chain coordinates."
                ),
            )
        if "phenomenological_nearest_neighbor_stiffness" in task.assumptions:
            report.add(
                id="stripe_stiffness_review",
                status="pass",
                severity="info",
                message="Wall-chain stiffness k is explicitly phenomenological.",
                evidence="phenomenological_nearest_neighbor_stiffness",
            )
        else:
            report.add(
                id="stripe_stiffness_review",
                status="review",
                severity="review",
                message="Verify the wall-chain stiffness k against the chosen stripe ansatz.",
                evidence=str(physics_ir.ansatz.collective_coordinates),
                recommendation=(
                    "Derive or cite the relation between the stripe displacement ansatz and the "
                    "effective stiffness k before treating it as a fitted parameter."
                ),
            )

    if texture.get("topology") == "half_integer_Q" and "compute_topological_charge" not in task.goals:
        report.add(
            id="meron_topology_goal",
            status="review",
            severity="warning",
            message="Meron-like texture should include topological-charge computation.",
            evidence="texture topology=half_integer_Q",
            recommendation="Add compute_topological_charge to goals.",
        )

    if task.texture == "meron":
        report.add(
            id="meron_boundary_conditions",
            status="review",
            severity="review",
            message="Confirm the boundary condition corresponds to a single meron.",
            evidence="texture=meron",
            recommendation="Distinguish half-integer meron charge from full skyrmion charge.",
        )
        report.add(
            id="core_polarity_helicity",
            status="review",
            severity="review",
            message="Check core polarity and helicity conventions for the topology sign.",
            evidence="texture=meron",
            recommendation="Record the sign convention used for core polarity and helicity.",
        )

    if task.texture == "vortex":
        report.add(
            id="vortex_winding_review",
            status="review",
            severity="review",
            message="Distinguish winding number from skyrmion charge for a vortex.",
            evidence="texture=vortex",
            recommendation="Report winding number separately from any Q-like integral.",
        )
        report.add(
            id="core_polarity_review",
            status="review",
            severity="review",
            message="Check how vortex core polarity affects any skyrmion-charge-like integral.",
            evidence="texture=vortex",
            recommendation="Do not conflate in-plane winding with core-polarity-dependent charge.",
        )

    if task.material == "ferromagnet" and task.texture in {"skyrmion", "antiskyrmion"}:
        report.add(
            id="gyro_sign_convention",
            status="review",
            severity="review",
            message="Check sign conventions for gyrotropic tensor G and topological charge Q.",
            evidence=physics_ir.dynamics.expected_equation_type,
            recommendation="Record the orientation convention for zhat, Q, and the cross product.",
        )

    if task.material == "ferromagnet" and task.texture == "antiskyrmion":
        if "positive_elliptic_scales" in task.assumptions:
            report.add(
                id="antiskyrmion_elliptic_axes",
                status="pass",
                severity="info",
                message="Positive elliptic scales lambdaX and lambdaY are declared along principal axes.",
                evidence="lambdaX>0, lambdaY>0",
            )
        else:
            report.add(
                id="antiskyrmion_elliptic_axes",
                status="review",
                severity="review",
                message="Antiskyrmion elliptic axes and scale signs require review.",
                recommendation="Declare positive lambdaX/lambdaY along the DMI principal axes.",
            )
        if "dmi_selected_antiskyrmion_helicity" in task.assumptions:
            report.add(
                id="antiskyrmion_helicity_selection",
                status="pass",
                severity="info",
                message="Fixed antiskyrmion helicity is declared to be selected by anisotropic DMI.",
                evidence="dmi_selected_antiskyrmion_helicity",
            )
        else:
            report.add(
                id="antiskyrmion_helicity_selection",
                status="review",
                severity="review",
                message="Antiskyrmion helicity selection requires review.",
                recommendation="Project the anisotropic DMI energy and verify the helicity stationary point.",
            )

    if task.material == "collinear_antiferromagnet" and task.texture == "skyrmion":
        report.add(
            id="afm_skyrmion_no_fm_thiele",
            status="pass",
            severity="info",
            message="AFM skyrmion route uses inertial dynamics, not FM Thiele dynamics.",
            evidence=template.name,
        )
        if {
            "opposite_sublattice_textures",
            "equal_sublattice_spin_densities",
        }.issubset(set(task.assumptions)):
            report.add(
                id="afm_compensation_sign_convention",
                status="pass",
                severity="info",
                message="Opposite textures and equal sublattice spin densities are declared.",
                evidence="Q_B=-Q_A and s_B=s_A",
            )
        else:
            report.add(
                id="afm_compensation_sign_convention",
                status="review",
                severity="review",
                message="Check compensation assumptions and sublattice sign conventions.",
                evidence=physics_ir.dynamics.gyrotropic_term or "",
                recommendation=(
                    "Verify that the two sublattice gyrotropic terms cancel with the chosen "
                    "definition of the Neel order parameter."
                ),
            )

    for index, limit_check in enumerate(physics_ir.limit_checks, start=1):
        report.add(
            id=f"limit_check_{index}",
            status="review",
            severity="info",
            message=f"Limit check to verify: {limit_check}",
            evidence=limit_check,
        )

    return report
