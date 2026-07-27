import pytest

from spintexture_agent.generator import PROJECT_ROOT
from spintexture_agent.wolfram import RESULT_BEGIN, RESULT_END, execute_wolfram_script


def test_dmi_variational_derivatives_match_analytic_results(tmp_path):
    package_path = (PROJECT_ROOT / "mathematica" / "SpinTextureTheory.wl").as_posix()
    script_path = tmp_path / "dmi_variational_regression.wl"
    script_path.write_text(
        f'''Get["{package_path}"];
ClearAll[x, y, z, nx, ny, nz, mx, my, mz, dCoeff];
n2 = {{nx[x, y], ny[x, y], nz[x, y]}};
m3 = {{mx[x, y, z], my[x, y, z], mz[x, y, z]}};

interfacialActual = EulerLagrangeVector[
  InterfacialDMIDensity[n2, {{x, y}}, dCoeff, 3], n2, {{x, y}}
];
interfacialExpected = 2 dCoeff {{-D[n2[[3]], x], -D[n2[[3]], y],
  D[n2[[1]], x] + D[n2[[2]], y]}};

anisotropicActual = EulerLagrangeVector[
  AnisotropicDMIDensity[n2, {{x, y}}, dCoeff, 3], n2, {{x, y}}
];
anisotropicExpected = 2 dCoeff {{-D[n2[[3]], x], D[n2[[3]], y],
  D[n2[[1]], x] - D[n2[[2]], y]}};

bulkActual = EulerLagrangeVector[
  BulkDMIDensity[m3, {{x, y, z}}, dCoeff], m3, {{x, y, z}}
];
bulkExpected = 2 dCoeff Curl[m3, {{x, y, z}}];

results = <|
  "interfacial" -> TrueQ[FullSimplify[interfacialActual - interfacialExpected] === {{0, 0, 0}}],
  "anisotropic" -> TrueQ[FullSimplify[anisotropicActual - anisotropicExpected] === {{0, 0, 0}}],
  "bulk" -> TrueQ[FullSimplify[bulkActual - bulkExpected] === {{0, 0, 0}}],
  "coefficient_used_as_function" -> Not[FreeQ[
    {{interfacialActual, anisotropicActual, bulkActual}}, dCoeff[__]
  ]]
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
        "interfacial": True,
        "anisotropic": True,
        "bulk": True,
        "coefficient_used_as_function": False,
    }
