from __future__ import annotations

from .capabilities import CapabilityRegistry
from .kb import KnowledgeBase
from .schema import (
    AnsatzIR,
    ConfidenceIR,
    DimensionContractIR,
    DynamicsIR,
    EvidenceAxisIR,
    EvidenceStatusIR,
    OrderParameterIR,
    PhysicsIR,
    TheoryTask,
)
from .selector import SelectedTemplate


def _topology_field(material_key: str) -> str:
    if material_key == "ferromagnet":
        return "m"
    if material_key == "collinear_antiferromagnet":
        return "n"
    if material_key in {"ferrimagnet", "noncollinear_antiferromagnet"}:
        return "sublattice_resolved"
    return "order_parameter"


def _expected_equation_type(task: TheoryTask, template: SelectedTemplate) -> str:
    if "compute_topological_charge" in task.goals and not any(
        goal.startswith("derive_") for goal in task.goals
    ):
        return "topology_only"
    if template.reduced_model:
        return template.reduced_model
    if template.dynamics == "sigma_model":
        return "second_order_sigma_model"
    if template.dynamics == "llg":
        return "first_order_llg"
    return template.dynamics


def _support_level(
    task: TheoryTask, template: SelectedTemplate, energy_terms: list[str]
) -> str:
    if task.material in {"ferrimagnet", "altermagnet", "noncollinear_antiferromagnet"}:
        return "review_only"
    if "dmi_unspecified" in energy_terms:
        return "review_only"
    topology_only = "compute_topological_charge" in task.goals and not any(
        goal.startswith("derive_") for goal in task.goals
    )
    if topology_only:
        full_meron_assumptions = {
            "unit_magnetization",
            "axisymmetric_meron_profile",
            "core_boundary_theta_zero",
            "far_field_theta_pi_over_two",
            "unit_winding_magnitude",
            "symbolic_core_polarity",
        }
        full_vortex_assumptions = {
            "unit_magnetization",
            "winding_number_texture",
            "single_valued_in_plane_phase",
            "unit_vorticity_magnitude",
            "finite_core_regularization",
            "core_polarity_sets_out_of_plane_component",
        }
        full_bimeron_assumptions = {
            "unit_magnetization",
            "paired_meron_ansatz",
            "constituent_meron_boundary_conditions",
            "additive_constituent_topological_charge",
            "opposite_core_polarities",
            "opposite_winding_numbers",
            "unit_constituent_winding_magnitude",
            "well_separated_meron_pair",
        }
        if task.material == "ferromagnet" and task.texture == "meron" and (
            full_meron_assumptions.issubset(set(task.assumptions))
        ):
            return "full_derivation"
        if task.material == "ferromagnet" and task.texture == "vortex" and (
            full_vortex_assumptions.issubset(set(task.assumptions))
        ):
            return "full_derivation"
        if task.material == "ferromagnet" and task.texture == "bimeron" and (
            full_bimeron_assumptions.issubset(set(task.assumptions))
        ):
            return "full_derivation"
        return "scaffold"
    full_afm_stripe_assumptions = {
        "sot_force_density_explicit",
        "symbolic_spin_polarization",
        "pinned_internal_wall_angles",
        "phenomenological_nearest_neighbor_stiffness",
        "periodic_wall_chain",
        "localized_wall_boundary_terms_vanish",
    }
    if (
        task.material == "collinear_antiferromagnet"
        and task.texture == "stripe_domain"
        and full_afm_stripe_assumptions.issubset(set(task.assumptions))
    ):
        return "full_derivation"
    full_fm_antiskyrmion_assumptions = {
        "rigid_antiskyrmion",
        "elliptical_antiskyrmion_profile",
        "antiskyrmion_winding_minus_one",
        "core_boundary_theta_pi",
        "far_field_theta_zero",
        "localized_texture_boundary_terms_vanish",
        "in_plane_spin_polarization",
        "explicit_llg_sot_torque",
        "fixed_helicity",
        "positive_elliptic_scales",
        "translationally_invariant_film",
        "dmi_selected_antiskyrmion_helicity",
    }
    if (
        task.material == "ferromagnet"
        and task.texture == "antiskyrmion"
        and "anisotropic_dmi" in energy_terms
        and full_fm_antiskyrmion_assumptions.issubset(set(task.assumptions))
    ):
        return "full_derivation"
    full_fm_skyrmion_assumptions = {
        "axisymmetric_skyrmion_profile",
        "unit_winding_number",
        "core_boundary_theta_pi",
        "far_field_theta_zero",
        "localized_texture_boundary_terms_vanish",
        "in_plane_spin_polarization",
        "explicit_llg_sot_torque",
        "fixed_helicity",
    }
    if (
        task.material == "ferromagnet"
        and task.texture == "skyrmion"
        and full_fm_skyrmion_assumptions.issubset(set(task.assumptions))
    ):
        return "full_derivation"
    full_afm_skyrmion_assumptions = {
        "compensated_two_sublattice_afm",
        "axisymmetric_skyrmion_profile",
        "unit_winding_number",
        "core_boundary_theta_pi",
        "far_field_theta_zero",
        "localized_texture_boundary_terms_vanish",
        "in_plane_spin_polarization",
        "explicit_sigma_model_force_density",
        "fixed_helicity",
        "opposite_sublattice_textures",
        "equal_sublattice_spin_densities",
        "translationally_invariant_film",
    }
    if (
        task.material == "collinear_antiferromagnet"
        and task.texture == "skyrmion"
        and full_afm_skyrmion_assumptions.issubset(set(task.assumptions))
    ):
        return "full_derivation"
    scaffolded_templates = {
        ("collinear_antiferromagnet", "stripe_domain"),
        ("collinear_antiferromagnet", "skyrmion"),
        ("ferromagnet", "skyrmion"),
        ("ferromagnet", "antiskyrmion"),
    }
    if (task.material, task.texture) in scaffolded_templates and not template.name.startswith("generic_"):
        return "scaffold"
    return "unsupported" if template.name.startswith("generic_") else "scaffold"


def _energy_terms(task: TheoryTask) -> list[str]:
    terms = ["exchange"]
    params = {key.lower(): value.lower() for key, value in task.parameters.items()}

    if "k" in params:
        terms.append("easy_axis_anisotropy")

    if "d" in params:
        dmi_label = params["d"]
        assumptions = " ".join(task.assumptions).lower()
        if (
            "anisotropic" in dmi_label
            or "anisotropic_dmi" in assumptions
            or "anisotropic dmi" in assumptions
        ):
            terms.append("anisotropic_dmi")
        elif (
            "interfacial" in dmi_label
            or "rashba" in dmi_label
            or "thin_film" in str(task.geometry)
            or "interfacial" in assumptions
        ):
            terms.append("interfacial_dmi")
        elif "bulk" in dmi_label:
            terms.append("bulk_dmi")
        else:
            terms.append("dmi_unspecified")

    if task.drive:
        terms.append(task.drive)

    return terms


def _dimension_contract(task: TheoryTask) -> DimensionContractIR | None:
    if task.material == "collinear_antiferromagnet" and task.texture == "stripe_domain":
        return DimensionContractIR(
            basis=["energy", "length", "time"],
            convention="one_dimensional_energy_per_transverse_area",
            assignments={
                "n": "1",
                "x, X_i, Delta": "L",
                "Phi_i, p, alpha": "1",
                "A": "E L",
                "K": "E L^-1",
                "D": "E",
                "chi": "E T^2 L^-1",
                "s": "E T L^-1",
                "tauDL, tauFL": "E L^-1",
                "k": "E L^-2",
                "M_XX": "E T^2 L^-2",
                "Gamma_XX": "E T L^-2",
                "F_X": "E L^-1",
                "M_PhiPhi": "E T^2",
                "Gamma_PhiPhi": "E T",
                "F_Phi": "E",
            },
            expected_equation_dimensions={
                "translation_terms": "E L^-1",
                "internal_angle_terms": "E",
                "energy_density_1d": "E L^-1",
            },
        )
    if task.material == "ferromagnet" and task.texture in {"skyrmion", "antiskyrmion"}:
        return DimensionContractIR(
            basis=["energy", "length", "time"],
            convention=(
                "two_dimensional_elliptic_antiskyrmion"
                if task.texture == "antiskyrmion"
                else "two_dimensional_energy_functional"
            ),
            assignments={
                "m, p, alpha, Q, Dsk": "1",
                "x, y, X, Y, R0, Delta, lambdaX, lambdaY": "L",
                "A": "E",
                "K": "E L^-2",
                "D": "E L^-1",
                "s": "E T L^-2",
                "tauDL, tauFL": "T^-1",
                "G_ij, Gamma_ij": "E T L^-2",
                "F_i": "E L^-1",
            },
            expected_equation_dimensions={
                "energy_density_2d": "E L^-2",
                "thiele_equation_terms": "E L^-1",
            },
        )
    if task.material == "collinear_antiferromagnet" and task.texture == "skyrmion":
        return DimensionContractIR(
            basis=["energy", "length", "time"],
            convention="two_dimensional_afm_sigma_model",
            assignments={
                "n, p, alpha, Q, Dsk": "1",
                "x, y, X, Y, R0, Delta": "L",
                "A": "E",
                "K": "E L^-2",
                "D": "E L^-1",
                "chi": "E T^2 L^-2",
                "s": "E T L^-2",
                "tauDL, tauFL": "E L^-2",
                "M_ij": "E T^2 L^-2",
                "Gamma_ij": "E T L^-2",
                "F_i": "E L^-1",
            },
            expected_equation_dimensions={
                "energy_density_2d": "E L^-2",
                "inertial_equation_terms": "E L^-1",
            },
        )
    if task.material == "ferromagnet" and task.texture in {"meron", "bimeron", "vortex"}:
        return DimensionContractIR(
            basis=["length"],
            convention="dimensionless_topological_invariant",
            assignments={
                "m, theta, phase, winding, polarity, p1, p2, w1, w2, Q, W": "1",
                "r, x, y": "L",
                "topological_density": "L^-2",
                "area_element": "L^2",
            },
            expected_equation_dimensions={
                "topological_charge": "1",
                "winding_number": "1",
            },
        )
    return None


def _gyrotropic_term(task: TheoryTask) -> str | None:
    if task.material == "ferromagnet" and task.texture in {"skyrmion", "antiskyrmion"}:
        return "present"
    if task.material == "collinear_antiferromagnet":
        return "cancelled_in_compensated_limit"
    if task.material == "ferrimagnet":
        return "compensation_dependent"
    return None


def _limit_checks(task: TheoryTask, energy_terms: list[str]) -> list[str]:
    if "compute_topological_charge" in task.goals and not any(
        goal.startswith("derive_") for goal in task.goals
    ):
        return []
    checks = ["alpha -> 0 gives conservative dynamics"]
    if any("dmi" in term for term in energy_terms):
        checks.append("D -> 0 removes chirality selection")
    if task.material == "collinear_antiferromagnet":
        checks.append("compensated AFM limit cancels gyrotropic term")
    return checks


def _confidence(task: TheoryTask, template: SelectedTemplate, energy_terms: list[str]) -> ConfidenceIR:
    generic_template = template.name.startswith("generic_")
    uncertain_dmi = "dmi_unspecified" in energy_terms
    anisotropic_dmi = "anisotropic_dmi" in energy_terms
    complex_material = task.material in {"noncollinear_antiferromagnet", "altermagnet"}

    topology_is_complex = task.material in {
        "ferrimagnet",
        "noncollinear_antiferromagnet",
        "altermagnet",
    }
    low_confidence_model = generic_template or complex_material

    return ConfidenceIR(
        model_selection=0.65 if low_confidence_model else 0.92,
        ansatz_validity=0.7 if low_confidence_model else 0.82,
        topology_definition=0.72 if topology_is_complex else 0.88,
        requires_human_review=generic_template or uncertain_dmi or anisotropic_dmi or complex_material,
    )


def build_physics_ir(task: TheoryTask, template: SelectedTemplate, kb: KnowledgeBase) -> PhysicsIR:
    material = kb.material(task.material)
    texture = kb.texture(task.texture)
    energy_terms = _energy_terms(task)
    order_parameters = list(material.get("order_parameters", []))
    primary = order_parameters[0] if order_parameters else "order_parameter"
    registry = CapabilityRegistry()
    route = registry.match_task(task)
    inferred_support = _support_level(task, template, energy_terms)
    if route is not None:
        support_level = route.support_level
        evidence_status = route.resolved_evidence_status(
            registry.data.evidence_status_schema_version
        )
        knowledge_status = evidence_status.compatibility_knowledge_status
        permitted_claim = route.permitted_claim
        blocked_claims = route.blocked_claims
        evidence_refs = route.all_evidence_refs()
        missing_evidence = route.missing_evidence
        promotion_requirements = route.promotion_requirements
        capability_limitations = route.limitations
    else:
        support_level = (
            inferred_support
            if inferred_support in {"review_only", "unsupported"}
            else "scaffold"
        )
        knowledge_status = "candidate"
        evidence_status = EvidenceStatusIR(
            schema_version=registry.data.evidence_status_schema_version,
            claim_class="candidate_extension",
            cas_execution=EvidenceAxisIR(status="missing"),
            analytic_reproduction=EvidenceAxisIR(status="missing"),
            literature_reproduction=EvidenceAxisIR(status="missing"),
            assertion_coverage=EvidenceAxisIR(status="missing"),
            benchmark=EvidenceAxisIR(status="missing"),
            cross_engine=EvidenceAxisIR(status="missing"),
            external_review=EvidenceAxisIR(status="pending"),
            public_release=EvidenceAxisIR(status="missing"),
            compatibility_knowledge_status="candidate",
        )
        permitted_claim = (
            "Provisional model-selection guidance and an inspectable candidate "
            "Physics IR for expert review."
        )
        blocked_claims = [
            "A complete or validated derivation for this unregistered task profile."
        ]
        evidence_refs = []
        missing_evidence = [
            "No released capability route matches the complete task profile.",
            "Symmetry, boundary conditions, and model assumptions require review.",
            "No route-specific executable benchmark evidence is registered.",
        ]
        promotion_requirements = [
            "Register a candidate route with sourced symmetry and model evidence.",
            "Complete CAS, limit, dimension, boundary, and negative-case checks.",
            "Obtain expert approval before claiming formal support.",
        ]
        capability_limitations = [
            "The generated route is provisional and cannot support a final physics claim."
        ]

    confidence = _confidence(task, template, energy_terms)
    if route is not None:
        confidence_updates: dict[str, float | bool] = {
            "requires_human_review": route.requires_human_review
        }
        if route.support_level == "full_derivation":
            confidence_updates["model_selection"] = max(
                confidence.model_selection, 0.92
            )
            confidence_updates["ansatz_validity"] = max(
                confidence.ansatz_validity, 0.82
            )
        confidence = confidence.model_copy(update=confidence_updates)
    else:
        confidence = confidence.model_copy(update={"requires_human_review": True})

    return PhysicsIR(
        task_name=task.task_name,
        material_class=task.material,
        texture_class=task.texture,
        drive=task.drive,
        geometry=task.geometry,
        support_level=support_level,
        knowledge_status=knowledge_status,
        evidence_status=evidence_status,
        permitted_claim=permitted_claim,
        blocked_claims=blocked_claims,
        capability_route_id=route.route_id if route else None,
        capability_registry_version=registry.data.schema_version,
        evidence_refs=evidence_refs,
        missing_evidence=missing_evidence,
        promotion_requirements=promotion_requirements,
        capability_limitations=capability_limitations,
        dimension_contract=_dimension_contract(task),
        order_parameter=OrderParameterIR(
            primary=primary,
            auxiliary=order_parameters[1:],
            constraints=list(material.get("constraints", [])),
            topology_field=_topology_field(task.material),
        ),
        energy_terms=energy_terms,
        dynamics=DynamicsIR(
            type=template.dynamics,
            inertial_term=template.dynamics in {"sigma_model", "two_sublattice_llg"},
            gyrotropic_term=_gyrotropic_term(task),
            expected_equation_type=_expected_equation_type(task, template),
        ),
        ansatz=AnsatzIR(
            type=template.ansatz,
            collective_coordinates=list(texture.get("collective_coordinates", [])),
            validity=list(task.assumptions),
        ),
        analysis=list(task.goals),
        assumptions=list(task.assumptions),
        validity_limits=list(task.assumptions),
        limit_checks=_limit_checks(task, energy_terms),
        confidence=confidence,
    )
