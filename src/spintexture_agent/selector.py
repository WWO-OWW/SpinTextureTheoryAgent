from __future__ import annotations

from dataclasses import dataclass

from .kb import KnowledgeBase
from .schema import TheoryTask


@dataclass(frozen=True)
class SelectedTemplate:
    name: str
    dynamics: str
    order_parameters: list[str]
    ansatz: str
    reduced_model: str | None
    notes: list[str]


def select_template(task: TheoryTask, kb: KnowledgeBase) -> SelectedTemplate:
    material = kb.material(task.material)
    texture = kb.texture(task.texture)

    if task.material == "collinear_antiferromagnet" and task.texture == "stripe_domain":
        name = "afm_stripe_domain_collective_coordinate"
        reduced_model = "coupled_wall_chain"
    elif task.material == "altermagnet" and task.texture == "stripe_domain":
        name = "altermagnet_stripe_tensor_review"
        reduced_model = "anisotropic_wall_chain_review"
    elif task.material == "ferromagnet" and task.texture in {"skyrmion", "antiskyrmion"}:
        name = "fm_skyrmion_thiele"
        reduced_model = "thiele_equation"
    elif task.material == "collinear_antiferromagnet" and task.texture == "skyrmion":
        name = "afm_skyrmion_inertial"
        reduced_model = "inertial_collective_coordinate"
    else:
        name = f"generic_{task.material}_{task.texture}"
        reduced_model = texture.get("reduced_model")

    return SelectedTemplate(
        name=name,
        dynamics=material["dynamics"],
        order_parameters=material["order_parameters"],
        ansatz=texture["ansatz"],
        reduced_model=reduced_model,
        notes=material.get("notes", []) + texture.get("notes", []),
    )
