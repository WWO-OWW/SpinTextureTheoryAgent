from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

import yaml

from .schema import TheoryTask


class PromptParseError(ValueError):
    """Raised when a prompt cannot be safely converted into a theory task."""


@dataclass(frozen=True)
class PromptParseReport:
    task: TheoryTask
    matched_aliases: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AliasEntry:
    key: str
    aliases: tuple[str, ...]


MATERIAL_ALIASES = (
    AliasEntry(
        "noncollinear_antiferromagnet",
        (
            "noncollinear antiferromagnet",
            "non-collinear antiferromagnet",
            "noncollinear afm",
            "120-degree antiferromagnet",
            "非共线反铁磁",
            "非共线 afm",
            "三子晶格反铁磁",
        ),
    ),
    AliasEntry(
        "altermagnet",
        (
            "altermagnetic antiferromagnet",
            "altermagnet",
            "altermagnetic",
            "交错磁体",
            "交错磁",
        ),
    ),
    AliasEntry(
        "collinear_antiferromagnet",
        (
            "collinear antiferromagnet",
            "compensated antiferromagnet",
            "antiferromagnet",
            "afm",
            "反铁磁",
            "补偿反铁磁",
            "共线反铁磁",
        ),
    ),
    AliasEntry(
        "ferrimagnet",
        (
            "ferrimagnet",
            "ferrimagnetic",
            "亚铁磁",
        ),
    ),
    AliasEntry(
        "ferromagnet",
        (
            "ferromagnet",
            "ferromagnetic",
            "fm",
            "铁磁",
        ),
    ),
)


TEXTURE_ALIASES = (
    AliasEntry(
        "antiskyrmion",
        (
            "anti-skyrmion",
            "antiskyrmion",
            "反斯格明子",
            "反 skyrmion",
        ),
    ),
    AliasEntry(
        "skyrmion",
        (
            "skyrmion",
            "skyrmions",
            "斯格明子",
        ),
    ),
    AliasEntry(
        "stripe_domain",
        (
            "stripe domain",
            "stripe-domain",
            "stripe",
            "domain-wall array",
            "domain wall array",
            "wall-chain",
            "wall chain",
            "条纹畴",
            "条纹",
            "畴壁链",
            "畴壁阵列",
        ),
    ),
    AliasEntry(
        "domain_wall",
        (
            "domain wall",
            "domain-wall",
            "畴壁",
        ),
    ),
    AliasEntry(
        "bimeron",
        (
            "bimeron",
            "双半子",
            "双 meron",
        ),
    ),
    AliasEntry(
        "meron",
        (
            "meron",
            "half-skyrmion",
            "half skyrmion",
            "半斯格明子",
        ),
    ),
    AliasEntry(
        "vortex",
        (
            "vortex",
            "涡旋",
            "磁涡旋",
        ),
    ),
)


DRIVE_ALIASES = (
    AliasEntry(
        "spin_orbit_torque",
        (
            "spin-orbit torque",
            "spin orbit torque",
            "sot",
            "自旋轨道力矩",
            "自旋轨道矩",
        ),
    ),
    AliasEntry(
        "spin_transfer_torque",
        (
            "spin-transfer torque",
            "spin transfer torque",
            "stt",
            "自旋转移力矩",
        ),
    ),
    AliasEntry(
        "temperature_gradient",
        (
            "temperature gradient",
            "thermal gradient",
            "热梯度",
            "温度梯度",
        ),
    ),
    AliasEntry(
        "magnetic_field",
        (
            "magnetic field",
            "field driven",
            "field-driven",
            "外磁场",
            "磁场驱动",
        ),
    ),
)


GEOMETRY_ALIASES = (
    AliasEntry(
        "thin_film_2d",
        (
            "thin-film",
            "thin film",
            "film",
            "2d",
            "two-dimensional",
            "二维",
            "薄膜",
        ),
    ),
    AliasEntry(
        "generic_2d",
        (
            "generic 2d",
            "2d system",
            "二维体系",
        ),
    ),
)


SHORT_LABELS = {
    "collinear_antiferromagnet": "afm",
    "noncollinear_antiferromagnet": "noncollinear_afm",
    "ferromagnet": "fm",
    "ferrimagnet": "ferri",
    "altermagnet": "altermagnet",
    "stripe_domain": "stripe",
    "domain_wall": "domain_wall",
    "skyrmion": "skyrmion",
    "antiskyrmion": "antiskyrmion",
    "meron": "meron",
    "bimeron": "bimeron",
    "vortex": "vortex",
    "spin_orbit_torque": "sot",
    "spin_transfer_torque": "stt",
    "temperature_gradient": "thermal",
    "magnetic_field": "field",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _contains_alias(text: str, alias: str) -> bool:
    alias = alias.lower()
    if alias.isascii() and re.search(r"[a-z0-9]", alias):
        return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text) is not None
    return alias in text


def _match(text: str, entries: Iterable[AliasEntry]) -> tuple[str | None, str | None]:
    for entry in entries:
        for alias in entry.aliases:
            if _contains_alias(text, alias):
                return entry.key, alias
    return None, None


def _has_any(text: str, aliases: Iterable[str]) -> bool:
    return any(_contains_alias(text, alias) for alias in aliases)


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _task_name(material: str, texture: str, drive: str | None) -> str:
    parts = [SHORT_LABELS.get(material, material), SHORT_LABELS.get(texture, texture)]
    if drive:
        parts.append(SHORT_LABELS.get(drive, drive))
    return "_".join(parts)


def _infer_goals(text: str, material: str, texture: str, drive: str | None) -> list[str]:
    derive_requested = _has_any(text, ("derive", "derivation", "equation", "dynamics", "推导", "方程", "动力学"))
    stability_requested = _has_any(text, ("stability", "stable", "dispersion", "稳定", "色散"))
    topology_requested = _has_any(text, ("topology", "topological", "charge", "winding", "拓扑", "拓扑荷", "绕数"))
    collective_requested = _has_any(text, ("collective coordinate", "projection", "集体坐标", "投影"))

    goals: list[str] = []

    if derive_requested or drive:
        if material == "ferromagnet":
            goals.append("derive_llg")
        elif material == "collinear_antiferromagnet":
            goals.append("derive_sigma_model")
        elif material == "ferrimagnet":
            goals.append("derive_two_sublattice_model")
        elif material == "altermagnet":
            goals.append("derive_anisotropic_afm_like_model")
        elif material == "noncollinear_antiferromagnet":
            goals.append("derive_multisublattice_model")

    if texture == "stripe_domain" and (derive_requested or drive or collective_requested):
        goals.append("collective_coordinate_projection")

    if material == "ferromagnet" and texture in {"skyrmion", "antiskyrmion"} and (
        derive_requested or drive
    ):
        goals.append("derive_thiele_equation")

    if material == "collinear_antiferromagnet" and texture == "skyrmion" and (
        derive_requested or drive
    ):
        goals.append("derive_inertial_collective_coordinate_equation")

    if stability_requested:
        goals.append("linear_stability")

    if topology_requested or texture in {"skyrmion", "antiskyrmion", "meron", "bimeron", "vortex"}:
        goals.append("compute_topological_charge")

    if not goals:
        goals.append("derive_collective_coordinate_equation")

    return _dedupe(goals)


def _dmi_parameter(text: str, texture: str, geometry: str | None) -> str | None:
    dmi_requested = _has_any(text, ("dmi", "dzyaloshinskii", "dzyaloshinskii-moriya", "dm interaction"))
    interfacial = _has_any(text, ("interfacial", "rashba", "界面", "薄膜"))
    bulk = _has_any(text, ("bulk dmi", "bulk", "体 dmi", "体dmi"))
    anisotropic = _has_any(text, ("anisotropic dmi", "anisotropic", "各向异性 dmi", "各向异性dmi"))

    if anisotropic or texture == "antiskyrmion":
        return "anisotropic_dmi"
    if interfacial or geometry == "thin_film_2d":
        return "interfacial_dmi"
    if bulk:
        return "bulk_dmi"
    if dmi_requested or texture in {"skyrmion", "stripe_domain"}:
        return "dmi_strength"
    return None


def _infer_parameters(
    text: str,
    material: str,
    texture: str,
    drive: str | None,
    geometry: str | None,
) -> dict[str, str]:
    params: dict[str, str] = {
        "A": "exchange_stiffness",
        "K": "effective_anisotropy",
        "alpha": "gilbert_damping",
    }

    dmi = _dmi_parameter(text, texture, geometry)
    if dmi:
        params["D"] = dmi

    if material == "ferromagnet":
        params["gamma"] = "gyromagnetic_ratio"
        params["Ms"] = "saturation_magnetization"
        params["s"] = "spin_density"
    elif material == "collinear_antiferromagnet":
        params["chi"] = "afm_susceptibility"
        params["s"] = "spin_density"
    elif material == "ferrimagnet":
        params["s_net"] = "net_spin_density"
    elif material == "altermagnet":
        params["Lambda"] = "crystal_symmetry_response_tensor"
    elif material == "noncollinear_antiferromagnet":
        params["J_sub"] = "sublattice_exchange_matrix"

    if drive == "spin_orbit_torque":
        params["tauDL"] = "damping_like_sot"
        if _has_any(text, ("field-like", "field like", "fl-sot", "场型", "类场")):
            params["tauFL"] = "field_like_sot"
    elif drive == "spin_transfer_torque":
        params["u"] = "spin_drift_velocity"
        params["beta"] = "nonadiabaticity"
    elif drive == "temperature_gradient":
        params["gradT"] = "temperature_gradient"
    elif drive == "magnetic_field":
        params["H"] = "magnetic_field"

    return params


def _infer_assumptions(
    text: str,
    material: str,
    texture: str,
    drive: str | None,
    geometry: str | None,
    parameters: dict[str, str],
) -> list[str]:
    assumptions: list[str] = []

    if material == "ferromagnet":
        assumptions.append("unit_magnetization")
    if material == "collinear_antiferromagnet":
        assumptions.extend(["strong_exchange_limit", "compensated_two_sublattice_afm"])
    if material == "ferrimagnet":
        assumptions.extend(["two_sublattice_ferrimagnet", "sublattice_resolved_topology_required"])
        if _has_any(text, ("compensation", "compensated", "补偿点", "角动量补偿")):
            assumptions.append("near_angular_momentum_compensation")
    if material == "altermagnet":
        assumptions.extend(
            [
                "crystal_symmetry_tensors_required",
                "anisotropic_sot_response",
                "human_review_required_for_torque_form",
            ]
        )
    if material == "noncollinear_antiferromagnet":
        assumptions.extend(["multi_order_parameter_required", "human_review_required"])

    if texture == "stripe_domain":
        assumptions.extend(["rigid_domain_wall", "constant_wall_width"])
    elif texture in {"skyrmion", "antiskyrmion"}:
        assumptions.append(f"rigid_{texture}")
        if material == "ferromagnet":
            assumptions.append("low_velocity")
        if material == "collinear_antiferromagnet":
            assumptions.append("gyrotropic_term_cancellation")
    elif texture == "meron":
        assumptions.extend(["meron_boundary_conditions", "half_integer_topological_charge"])
    elif texture == "vortex":
        assumptions.extend(["winding_number_texture", "core_polarity_sets_out_of_plane_component"])

    if "D" in parameters:
        if parameters["D"] == "dmi_strength":
            assumptions.append("dmi_symmetry_not_specified")
        elif parameters["D"] == "interfacial_dmi" and geometry == "thin_film_2d":
            assumptions.append("interfacial_dmi_optional")
        elif parameters["D"] == "anisotropic_dmi":
            assumptions.append("anisotropic_dmi_required")

    if drive == "spin_orbit_torque":
        assumptions.append("sot_polarization_requires_review")
    if _has_any(text, ("weak damping", "弱阻尼")):
        assumptions.append("weak_damping")
    if _has_any(text, ("low velocity", "低速")):
        assumptions.append("low_velocity")

    return _dedupe(assumptions)


def parse_natural_language_task(prompt: str, task_name: str | None = None) -> PromptParseReport:
    """Parse a controlled physics prompt into a conservative `TheoryTask`.

    The parser is intentionally rule based. It is meant to provide a transparent
    first pass from natural language to YAML, while the Physics IR and validator
    remain responsible for judging whether the inferred task is physically safe.
    """

    normalized = _normalize(prompt)
    if not normalized:
        raise PromptParseError("Prompt is empty.")

    material, material_alias = _match(normalized, MATERIAL_ALIASES)
    texture, texture_alias = _match(normalized, TEXTURE_ALIASES)
    drive, drive_alias = _match(normalized, DRIVE_ALIASES)
    geometry, geometry_alias = _match(normalized, GEOMETRY_ALIASES)

    missing: list[str] = []
    if material is None:
        missing.append("material")
    if texture is None:
        missing.append("texture")
    if missing:
        raise PromptParseError(
            "Cannot safely parse prompt; missing required field(s): " + ", ".join(missing)
        )

    assert material is not None
    assert texture is not None

    goals = _infer_goals(normalized, material, texture, drive)
    parameters = _infer_parameters(normalized, material, texture, drive, geometry)
    assumptions = _infer_assumptions(normalized, material, texture, drive, geometry, parameters)

    warnings: list[str] = []
    if drive is None:
        warnings.append("No drive was detected; generated task is drive-free.")
    if geometry is None:
        warnings.append("No geometry was detected; DMI symmetry may require manual review.")
    if material in {"altermagnet", "noncollinear_antiferromagnet"}:
        warnings.append(
            "Complex magnetic order detected; crystal or sublattice symmetry must be reviewed."
        )
    if parameters.get("D") == "dmi_strength":
        warnings.append("DMI was inferred without a symmetry class; validator should flag review.")

    matched_aliases = {
        key: value
        for key, value in {
            "material": material_alias,
            "texture": texture_alias,
            "drive": drive_alias,
            "geometry": geometry_alias,
        }.items()
        if value is not None
    }

    task = TheoryTask(
        task_name=task_name or _task_name(material, texture, drive),
        material=material,
        texture=texture,
        drive=drive,
        geometry=geometry,
        goals=goals,
        assumptions=assumptions,
        parameters=parameters,
    )
    return PromptParseReport(task=task, matched_aliases=matched_aliases, warnings=warnings)


def task_to_yaml(task: TheoryTask) -> str:
    return yaml.safe_dump(
        task.model_dump(exclude_none=True),
        allow_unicode=True,
        sort_keys=False,
    )
