import pytest

from spintexture_agent.generator import PROJECT_ROOT
from spintexture_agent.wolfram import RESULT_BEGIN, RESULT_END, execute_wolfram_script


def test_domain_wall_metric_and_sot_force_are_symbolically_integrated(tmp_path):
    package_path = (PROJECT_ROOT / "mathematica" / "SpinTextureTheory.wl").as_posix()
    script_path = tmp_path / "domain_wall_projection_regression.wl"
    script_path.write_text(
        f'''Get["{package_path}"];
ClearAll[x, Xc, Phic, Delta, wallPolarity, px, py, pz, tauDL, tauFL];
theta = 2 ArcTan[Exp[(x - Xc)/Delta]];
nDW = {{Sin[theta] Cos[Phic], Sin[theta] Sin[Phic], Cos[theta]}};
assumptions = Delta > 0 && Element[{{Xc, Phic}}, Reals];
metric = CollectiveMetricMatrix[
  nDW, {{Xc, Phic}}, {{{{x, -Infinity, Infinity}}}}, assumptions
];
expectedMetric = {{{{2/Delta, 0}}, {{0, 2 Delta}}}};
force = DomainWallSOTGeneralizedForce[
  Phic, Delta, wallPolarity, {{px, py, pz}}, tauDL, tauFL
];
expectedForce = {{
  wallPolarity (-2 pz tauDL + Pi py tauFL Cos[Phic] - Pi px tauFL Sin[Phic]),
  Delta (-2 pz tauFL - Pi py tauDL Cos[Phic] + Pi px tauDL Sin[Phic])
}};
results = <|
  "metric_regression" -> TrueQ[
    FullSimplify[metric - expectedMetric, assumptions] === ConstantArray[0, {{2, 2}}]
  ],
  "force_regression" -> TrueQ[
    FullSimplify[
      force - expectedForce,
      Delta > 0 && wallPolarity^2 == 1
    ] === {{0, 0}}
  ],
  "metric_contains_integrate" -> Not[FreeQ[metric, _Integrate]],
  "force_contains_integrate" -> Not[FreeQ[force, _Integrate]],
  "dimension_algebra" -> TrueQ[
    DimensionProduct[{{1, 0, 0}}, {{0, 1, 0}}] === {{1, 1, 0}} &&
    DimensionQuotient[{{1, 1, 0}}, {{0, 1, 0}}] === {{1, 0, 0}} &&
    DimensionPower[{{0, 0, 1}}, -2] === {{0, 0, -2}} &&
    DimensionEqualQ[{{1, -1, 0}}, {{1, -1, 0}}]
  ]
|>;
WriteString[$Output, "{RESULT_BEGIN}\\n"];
WriteString[$Output, ExportString[results, "JSON"] <> "\\n"];
WriteString[$Output, "{RESULT_END}\\n"];
''',
        encoding="utf-8",
    )

    execution = execute_wolfram_script(script_path, tmp_path / "logs", timeout_seconds=120)
    if execution.status == "skipped":
        pytest.skip(execution.reason or "Wolfram executable unavailable")

    assert execution.status == "passed", execution.stderr_excerpt
    assert execution.result == {
        "metric_regression": True,
        "force_regression": True,
        "metric_contains_integrate": False,
        "force_contains_integrate": False,
        "dimension_algebra": True,
    }


def test_axisymmetric_skyrmion_projection_is_symbolically_integrated(tmp_path):
    package_path = (PROJECT_ROOT / "mathematica" / "SpinTextureTheory.wl").as_posix()
    script_path = tmp_path / "skyrmion_projection_regression.wl"
    script_path.write_text(
        f'''Get["{package_path}"];
ClearAll[r, phi, helicity, polarity, theta, px, py, tauDL, tauFL, u];
m = AxisymmetricSkyrmionField[theta[r], phi, polarity, 1, helicity];
tangents = PolarTranslationTangents[m, r, phi];
assumptions = r > 0 && polarity^2 == 1 &&
  Element[{{r, helicity, polarity, px, py, tauDL, tauFL}}, Reals];
gyro = AngularCollectiveGyrotropicTensor[
  m, tangents, r, phi, 1, assumptions
];
metric = AngularCollectiveMetricMatrix[tangents, r, phi, assumptions];
dlForce = AngularLLGTorqueGeneralizedForce[
  m, tangents, SOTDrive[m, {{px, py, 0}}, tauDL, 0],
  r, phi, 1, assumptions
];
flForce = AngularLLGTorqueGeneralizedForce[
  m, tangents, SOTDrive[m, {{px, py, 0}}, 0, tauFL],
  r, phi, 1, assumptions
];
sigmaDLForce = AngularGeneralizedForceDensity[
  tangents, SOTDrive[m, {{px, py, 0}}, tauDL, 0], r, phi, assumptions
];
sigmaFLForce = AngularGeneralizedForceDensity[
  tangents, SOTDrive[m, {{px, py, 0}}, 0, tauFL], r, phi, assumptions
];
nOpposite = -m;
oppositeTangents = PolarTranslationTangents[nOpposite, r, phi];
oppositeGyro = AngularCollectiveGyrotropicTensor[
  nOpposite, oppositeTangents, r, phi, 1, assumptions
];
expectedGyro = 2 Pi polarity Sin[theta[r]] theta'[r] * {{{{0, 1}}, {{-1, 0}}}};
expectedMetric = Pi (Sin[theta[r]]^2/r + r theta'[r]^2) IdentityMatrix[2];
expectedDL = Pi polarity tauDL (
  Cos[theta[r]] Sin[theta[r]] + r theta'[r]
) {{py Cos[helicity] - px Sin[helicity], -(px Cos[helicity] + py Sin[helicity])}};
expectedFL = -Pi tauFL D[r Sin[theta[r]], r] *
  {{px Cos[helicity] + py Sin[helicity], py Cos[helicity] - px Sin[helicity]}};
expectedSigmaDL = Pi tauDL D[r Sin[theta[r]], r] *
  {{px Cos[helicity] + py Sin[helicity], py Cos[helicity] - px Sin[helicity]}};
expectedSigmaFL = Pi polarity tauFL (
  Cos[theta[r]] Sin[theta[r]] + r theta'[r]
) {{py Cos[helicity] - px Sin[helicity], -(px Cos[helicity] + py Sin[helicity])}};
results = <|
  "unit_norm" -> TrueQ[FullSimplify[m . m, assumptions] === 1],
  "topological_boundary_charge" -> TrueQ[
    FullSimplify[polarity/2 Integrate[Sin[u], {{u, Pi, 0}}]] === -polarity
  ],
  "gyro_regression" -> TrueQ[
    And @@ Map[PossibleZeroQ, Flatten[FullSimplify[gyro - expectedGyro, assumptions]]]
  ],
  "metric_regression" -> TrueQ[
    FullSimplify[metric - expectedMetric, assumptions] === ConstantArray[0, {{2, 2}}]
  ],
  "damping_like_force_regression" -> TrueQ[
    FullSimplify[dlForce - expectedDL, assumptions] === {{0, 0}}
  ],
  "field_like_boundary_regression" -> TrueQ[
    FullSimplify[flForce - expectedFL, assumptions] === {{0, 0}}
  ],
  "sigma_damping_like_boundary_regression" -> TrueQ[
    FullSimplify[sigmaDLForce - expectedSigmaDL, assumptions] === {{0, 0}}
  ],
  "sigma_field_like_force_regression" -> TrueQ[
    FullSimplify[sigmaFLForce - expectedSigmaFL, assumptions] === {{0, 0}}
  ],
  "opposite_sublattice_gyro_regression" -> TrueQ[
    FullSimplify[gyro + oppositeGyro, assumptions] === ConstantArray[0, {{2, 2}}]
  ]
|>;
WriteString[$Output, "{RESULT_BEGIN}\\n"];
WriteString[$Output, ExportString[results, "JSON"] <> "\\n"];
WriteString[$Output, "{RESULT_END}\\n"];
''',
        encoding="utf-8",
    )

    execution = execute_wolfram_script(script_path, tmp_path / "logs", timeout_seconds=120)
    if execution.status == "skipped":
        pytest.skip(execution.reason or "Wolfram executable unavailable")

    assert execution.status == "passed", execution.stderr_excerpt
    assert execution.result == {
        "unit_norm": True,
        "topological_boundary_charge": True,
        "gyro_regression": True,
        "metric_regression": True,
        "damping_like_force_regression": True,
        "field_like_boundary_regression": True,
        "sigma_damping_like_boundary_regression": True,
        "sigma_field_like_force_regression": True,
        "opposite_sublattice_gyro_regression": True,
    }


def test_elliptic_antiskyrmion_projection_is_anisotropic(tmp_path):
    package_path = (PROJECT_ROOT / "mathematica" / "SpinTextureTheory.wl").as_posix()
    script_path = tmp_path / "antiskyrmion_projection_regression.wl"
    script_path.write_text(
        f'''Get["{package_path}"];
ClearAll[r, phi, helicity, polarity, theta, px, py, tauDL, lambdaX, lambdaY, Dmi, u];
m = AxisymmetricSkyrmionField[theta[r], phi, polarity, -1, helicity];
baseTangents = PolarTranslationTangents[m, r, phi];
scaledTangents = {{baseTangents[[1]]/lambdaX, baseTangents[[2]]/lambdaY}};
jacobian = lambdaX lambdaY;
assumptions = r > 0 && lambdaX > 0 && lambdaY > 0 && polarity^2 == 1 &&
  Element[{{r, helicity, polarity, px, py, tauDL, lambdaX, lambdaY, Dmi}}, Reals];
metric = FullSimplify[
  jacobian AngularCollectiveMetricMatrix[scaledTangents, r, phi, assumptions],
  assumptions
];
gyro = FullSimplify[
  jacobian AngularCollectiveGyrotropicTensor[m, scaledTangents, r, phi, 1, assumptions],
  assumptions
];
dlForce = FullSimplify[
  jacobian AngularLLGTorqueGeneralizedForce[
    m, scaledTangents, SOTDrive[m, {{px, py, 0}}, tauDL, 0],
    r, phi, 1, assumptions
  ],
  assumptions
];
derivatives = ScaledPolarSpatialDerivatives[m, r, phi, lambdaX, lambdaY];
dx = derivatives[[1]];
dy = derivatives[[2]];
dmiDensity = Dmi (
  m[[3]] dx[[1]] - m[[1]] dx[[3]] - m[[3]] dy[[2]] + m[[2]] dy[[3]]
);
dmiAngular = FullSimplify[
  Integrate[
    jacobian r dmiDensity, {{phi, 0, 2 Pi}},
    Assumptions -> assumptions, GenerateConditions -> False
  ],
  assumptions
];
baseMetric = Pi (Sin[theta[r]]^2/r + r theta'[r]^2);
expectedMetric = baseMetric * {{{{lambdaY/lambdaX, 0}}, {{0, lambdaX/lambdaY}}}};
expectedGyro = -2 Pi polarity Sin[theta[r]] theta'[r] * {{{{0, 1}}, {{-1, 0}}}};
directionX = py Cos[helicity] - px Sin[helicity];
directionY = px Cos[helicity] + py Sin[helicity];
expectedDL = Pi polarity tauDL (
  Cos[theta[r]] Sin[theta[r]] + r theta'[r]
) {{lambdaY directionX, lambdaX directionY}};
expectedDMI = Pi Dmi polarity (lambdaX + lambdaY) Cos[helicity] (
  Cos[theta[r]] Sin[theta[r]] + r theta'[r]
);
results = <|
  "unit_norm" -> TrueQ[FullSimplify[m . m, assumptions] === 1],
  "antiskyrmion_charge" -> TrueQ[
    FullSimplify[-polarity/2 Integrate[Sin[u], {{u, Pi, 0}}]] === polarity
  ],
  "anisotropic_metric" -> TrueQ[
    FullSimplify[metric - expectedMetric, assumptions] === ConstantArray[0, {{2, 2}}]
  ],
  "opposite_winding_gyro" -> TrueQ[
    And @@ Map[PossibleZeroQ, Flatten[FullSimplify[gyro - expectedGyro, assumptions]]]
  ],
  "anisotropic_sot_force" -> TrueQ[
    FullSimplify[dlForce - expectedDL, assumptions] === {{0, 0}}
  ],
  "anisotropic_dmi_projection" -> TrueQ[
    FullSimplify[dmiAngular - expectedDMI, assumptions] === 0
  ]
|>;
WriteString[$Output, "{RESULT_BEGIN}\\n"];
WriteString[$Output, ExportString[results, "JSON"] <> "\\n"];
WriteString[$Output, "{RESULT_END}\\n"];
''',
        encoding="utf-8",
    )

    execution = execute_wolfram_script(script_path, tmp_path / "logs", timeout_seconds=120)
    if execution.status == "skipped":
        pytest.skip(execution.reason or "Wolfram executable unavailable")

    assert execution.status == "passed", execution.stderr_excerpt
    assert execution.result == {
        "unit_norm": True,
        "antiskyrmion_charge": True,
        "anisotropic_metric": True,
        "opposite_winding_gyro": True,
        "anisotropic_sot_force": True,
        "anisotropic_dmi_projection": True,
    }
