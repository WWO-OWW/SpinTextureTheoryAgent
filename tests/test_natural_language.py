from pathlib import Path

from spintexture_agent.checker import check_task
from spintexture_agent.ir import build_physics_ir
from spintexture_agent.kb import KnowledgeBase
from spintexture_agent.nl import PromptParseError, parse_natural_language_task, task_to_yaml
from spintexture_agent.schema import TheoryTask
from spintexture_agent.selector import select_template


def _ir_from_prompt(prompt: str):
    parsed = parse_natural_language_task(prompt)
    kb = KnowledgeBase()
    template = select_template(parsed.task, kb)
    physics_ir = build_physics_ir(parsed.task, template, kb)
    report = check_task(parsed.task, template, kb, physics_ir)
    return parsed, template, physics_ir, report


def test_parse_chinese_afm_stripe_sot_prompt():
    parsed, template, physics_ir, report = _ir_from_prompt(
        "二维反铁磁薄膜中，SOT 驱动条纹畴，推导条纹畴动力学方程并分析稳定性。"
    )

    assert parsed.task.task_name == "afm_stripe_sot"
    assert parsed.task.material == "collinear_antiferromagnet"
    assert parsed.task.texture == "stripe_domain"
    assert parsed.task.drive == "spin_orbit_torque"
    assert parsed.task.geometry == "thin_film_2d"
    assert "derive_sigma_model" in parsed.task.goals
    assert "collective_coordinate_projection" in parsed.task.goals
    assert "linear_stability" in parsed.task.goals
    assert parsed.task.parameters["D"] == "interfacial_dmi"
    assert template.name == "afm_stripe_domain_collective_coordinate"
    assert physics_ir.dynamics.expected_equation_type == "coupled_wall_chain"
    assert report.ok is True


def test_parse_fm_skyrmion_sot_prompt_routes_to_thiele():
    parsed, template, physics_ir, _ = _ir_from_prompt(
        "Ferromagnetic skyrmion driven by spin-orbit torque: derive the Thiele equation "
        "and compute the topological charge in a thin film."
    )

    assert parsed.task.material == "ferromagnet"
    assert parsed.task.texture == "skyrmion"
    assert "derive_llg" in parsed.task.goals
    assert "derive_thiele_equation" in parsed.task.goals
    assert "compute_topological_charge" in parsed.task.goals
    assert template.name == "fm_skyrmion_thiele"
    assert physics_ir.order_parameter.topology_field == "m"
    assert physics_ir.dynamics.expected_equation_type == "thiele_equation"


def test_parse_afm_skyrmion_sot_prompt_routes_to_inertial_model():
    parsed, template, physics_ir, report = _ir_from_prompt(
        "AFM skyrmion under SOT in a 2D thin film; derive the collective-coordinate "
        "dynamics and topology."
    )

    assert parsed.task.material == "collinear_antiferromagnet"
    assert parsed.task.texture == "skyrmion"
    assert "derive_inertial_collective_coordinate_equation" in parsed.task.goals
    assert template.name == "afm_skyrmion_inertial"
    assert physics_ir.dynamics.expected_equation_type == "inertial_collective_coordinate"
    assert physics_ir.dynamics.gyrotropic_term == "cancelled_in_compensated_limit"
    assert physics_ir.order_parameter.topology_field == "n"
    assert "afm_skyrmion_no_fm_thiele" in {item.id for item in report.items}


def test_parse_altermagnet_stripe_prompt_requires_human_review():
    parsed, _, physics_ir, _ = _ir_from_prompt(
        "交错磁体薄膜中 SOT 驱动条纹畴，推导动力学方程。"
    )

    assert parsed.task.material == "altermagnet"
    assert parsed.task.texture == "stripe_domain"
    assert "derive_anisotropic_afm_like_model" in parsed.task.goals
    assert "crystal_symmetry_tensors_required" in parsed.task.assumptions
    assert physics_ir.confidence.requires_human_review is True


def test_parse_altermagnetic_antiferromagnet_prefers_altermagnet():
    parsed = parse_natural_language_task(
        "Altermagnetic antiferromagnet stripe domain driven by SOT in a thin film."
    )

    assert parsed.task.material == "altermagnet"
    assert parsed.task.texture == "stripe_domain"


def test_parse_noncollinear_afm_skyrmion_requires_multisublattice_review():
    parsed, _, physics_ir, report = _ir_from_prompt(
        "非共线反铁磁薄膜中，skyrmion 受 SOT 驱动，推导多子晶格动力学并计算拓扑荷。"
    )

    assert parsed.task.material == "noncollinear_antiferromagnet"
    assert parsed.task.texture == "skyrmion"
    assert "derive_multisublattice_model" in parsed.task.goals
    assert physics_ir.order_parameter.topology_field == "sublattice_resolved"
    assert physics_ir.confidence.requires_human_review is True
    assert "noncollinear_order_parameter_review" in {item.id for item in report.items}


def test_parse_requires_material_and_texture():
    try:
        parse_natural_language_task("推导 SOT 驱动动力学方程")
    except PromptParseError as exc:
        assert "material" in str(exc)
        assert "texture" in str(exc)
    else:
        raise AssertionError("Expected PromptParseError")


def test_task_to_yaml_round_trip(tmp_path):
    parsed = parse_natural_language_task(
        "二维反铁磁薄膜中，SOT 驱动条纹畴，推导条纹畴动力学方程。"
    )
    path = tmp_path / "parsed.yaml"
    path.write_text(task_to_yaml(parsed.task), encoding="utf-8")

    task = TheoryTask.from_yaml(Path(path))
    assert task == parsed.task
