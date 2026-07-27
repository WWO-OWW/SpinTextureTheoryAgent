import pytest

from spintexture_agent.generator import PROJECT_ROOT
from spintexture_agent.wolfram import RESULT_BEGIN, RESULT_END, execute_wolfram_script


def test_boundary_charge_and_winding_are_evaluated_by_wolfram(tmp_path):
    package_path = (PROJECT_ROOT / "mathematica" / "SpinTextureTheory.wl").as_posix()
    script_path = tmp_path / "topology_boundary_regression.wl"
    script_path.write_text(
        f'''Get["{package_path}"];
ClearAll[polarity, winding, vorticity, phi, helicity, r, theta];
meronCharge = AxisymmetricTopologicalChargeFromBoundaries[0, Pi/2, winding, polarity];
skyrmionCharge = AxisymmetricTopologicalChargeFromBoundaries[Pi, 0, winding, polarity];
phase = vorticity phi + helicity;
vortexWinding = WindingNumberFromPhase[phase, phi];
bimeronCharge = CompositeMeronTopologicalCharge[
  {{polarity, -polarity}}, {{winding, -winding}}
];
trivialPairCharge = CompositeMeronTopologicalCharge[
  {{polarity, polarity}}, {{winding, -winding}}
];
boundaryField = {{Cos[phase], Sin[phase], 0}};
assumptions = polarity^2 == 1 && winding^2 == 1 && vorticity^2 == 1 &&
  Element[{{polarity, winding, vorticity}}, Integers] && Element[helicity, Reals];
radialDensity = RadialTopologicalDensity2D[theta[r], r, winding, polarity];
results = <|
  "meron_half_charge" -> TrueQ[
    FullSimplify[meronCharge - polarity winding/2, assumptions] === 0
  ],
  "meron_half_magnitude" -> TrueQ[
    FullSimplify[meronCharge^2, assumptions] === 1/4
  ],
  "skyrmion_integer_charge" -> TrueQ[
    FullSimplify[skyrmionCharge + polarity winding, assumptions] === 0
  ],
  "radial_density_structure" -> TrueQ[
    radialDensity === polarity winding Sin[theta[r]] theta'[r]/(4 Pi r)
  ],
  "vortex_winding" -> TrueQ[
    FullSimplify[vortexWinding - vorticity, assumptions] === 0
  ],
  "bimeron_integer_charge" -> TrueQ[
    FullSimplify[bimeronCharge - polarity winding, assumptions] === 0
  ],
  "bimeron_integer_magnitude" -> TrueQ[
    FullSimplify[bimeronCharge^2, assumptions] === 1
  ],
  "bimeron_trivial_pair_control" -> TrueQ[trivialPairCharge === 0],
  "mismatched_constituent_lists_rejected" -> TrueQ[
    CompositeMeronTopologicalCharge[{{1}}, {{1, -1}}] === $Failed
  ],
  "single_valued_boundary" -> TrueQ[
    FullSimplify[
      (boundaryField /. phi -> 2 Pi) - (boundaryField /. phi -> 0), assumptions
    ] === {{0, 0, 0}}
  ],
  "dimensionless_integral" -> TrueQ[
    DimensionProduct[DimensionPower[{{1}}, -2], DimensionPower[{{1}}, 2]] === {{0}}
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
        "meron_half_charge": True,
        "meron_half_magnitude": True,
        "skyrmion_integer_charge": True,
        "radial_density_structure": True,
        "vortex_winding": True,
        "bimeron_integer_charge": True,
        "bimeron_integer_magnitude": True,
        "bimeron_trivial_pair_control": True,
        "mismatched_constituent_lists_rejected": True,
        "single_valued_boundary": True,
        "dimensionless_integral": True,
    }
