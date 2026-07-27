(* Independent analytic gold path for B1. Do not load SpinTextureTheory.wl. *)
ClearAll["Global`*"];

ToGoldString[expr_String] := expr;
ToGoldString[expr_] := ToString[expr, InputForm];
goldResults = <||>;
GoldRecord[key_String, expr_] := (
  goldResults = Join[goldResults, <|key -> ToGoldString[expr]|>];
  expr
);

ClearAll[
  r, phi, theta, helicity, polarity, px, py, tauDL, tauFL,
  s, alpha, Dsk, Isot, Qsk, X, Y, t
];
assumptions = r > 0 && polarity^2 == 1 &&
  Element[{r, phi, helicity, polarity, px, py, tauDL, tauFL}, Reals];

m = {
  Sin[theta[r]] Cos[phi + helicity],
  Sin[theta[r]] Sin[phi + helicity],
  polarity Cos[theta[r]]
};
radialDerivative = D[m, r];
angularDerivative = D[m, phi];
tangentX = -(Cos[phi] radialDerivative - Sin[phi] angularDerivative/r);
tangentY = -(Sin[phi] radialDerivative + Cos[phi] angularDerivative/r);
tangents = {tangentX, tangentY};

metricAngularDensity = FullSimplify[
  Integrate[
    r Table[tangents[[i]] . tangents[[j]], {i, 2}, {j, 2}],
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
expectedMetricAngularDensity = Pi (
  Sin[theta[r]]^2/r + r theta'[r]^2
) IdentityMatrix[2];

geometricGyroAngularDensity = FullSimplify[
  Integrate[
    r Table[m . Cross[tangents[[i]], tangents[[j]]], {i, 2}, {j, 2}],
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
expectedGeometricGyroAngularDensity = 2 Pi polarity Sin[theta[r]] theta'[r] {
  {0, 1}, {-1, 0}
};

topologicalCharge = FullSimplify[
  polarity/2 Integrate[Sin[u], {u, Pi, 0}],
  polarity^2 == 1
];
Qsk = topologicalCharge;
geometricGyroTensor = 4 Pi Qsk {{0, 1}, {-1, 0}};
(* The LLG equation convention contributes minus the geometric tensor. *)
equationGyroTensor = FullSimplify[-s geometricGyroTensor];
dampingTensor = alpha s Dsk IdentityMatrix[2];

p = {px, py, 0};
dampingLikeTorque = tauDL Cross[m, Cross[m, p]];
fieldLikeTorque = tauFL Cross[m, p];
dampingLikeForceAngularDensity = FullSimplify[
  Integrate[
    r Table[dampingLikeTorque . Cross[m, tangents[[i]]], {i, 2}],
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
fieldLikeForceAngularDensity = FullSimplify[
  Integrate[
    r Table[fieldLikeTorque . Cross[m, tangents[[i]]], {i, 2}],
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
expectedDampingLikeForceAngularDensity = Pi polarity tauDL (
  Cos[theta[r]] Sin[theta[r]] + r theta'[r]
) {
  py Cos[helicity] - px Sin[helicity],
  -(px Cos[helicity] + py Sin[helicity])
};
expectedFieldLikeForceAngularDensity = -Pi tauFL D[r Sin[theta[r]], r] {
  px Cos[helicity] + py Sin[helicity],
  py Cos[helicity] - px Sin[helicity]
};
dampingLikeForce = Pi s polarity tauDL Isot {
  py Cos[helicity] - px Sin[helicity],
  -(px Cos[helicity] + py Sin[helicity])
};
fieldLikeBoundaryForce = {0, 0};

velocity = {X'[t], Y'[t]};
thieleEquation = Thread[
  equationGyroTensor . velocity + dampingTensor . velocity == dampingLikeForce
];

regressions = <|
  "unit_constraint" -> TrueQ[FullSimplify[m . m, assumptions] === 1],
  "topological_charge" -> TrueQ[topologicalCharge === -polarity],
  "metric_density" -> TrueQ[FullSimplify[metricAngularDensity - expectedMetricAngularDensity, assumptions] === ConstantArray[0, {2, 2}]],
  "geometric_gyro_density" -> TrueQ[FullSimplify[geometricGyroAngularDensity - expectedGeometricGyroAngularDensity, assumptions] === ConstantArray[0, {2, 2}]],
  "llg_gyro_sign_bridge" -> TrueQ[equationGyroTensor === 4 Pi s Qsk {{0, -1}, {1, 0}}],
  "damping_like_force_density" -> TrueQ[FullSimplify[dampingLikeForceAngularDensity - expectedDampingLikeForceAngularDensity, assumptions] === {0, 0}],
  "field_like_boundary_density" -> TrueQ[FullSimplify[fieldLikeForceAngularDensity - expectedFieldLikeForceAngularDensity, assumptions] === {0, 0}],
  "field_like_localized_boundary" -> True
|>;

GoldRecord["topological_charge", topologicalCharge];
GoldRecord["metric_angular_density", metricAngularDensity];
GoldRecord["geometric_gyrotropic_angular_density", geometricGyroAngularDensity];
GoldRecord["geometric_gyrotropic_tensor", geometricGyroTensor];
GoldRecord["equation_gyrotropic_tensor", equationGyroTensor];
GoldRecord["damping_tensor", dampingTensor];
GoldRecord["damping_like_force_angular_density", dampingLikeForceAngularDensity];
GoldRecord["damping_like_generalized_force", dampingLikeForce];
GoldRecord["field_like_boundary_force", fieldLikeBoundaryForce];
GoldRecord["thiele_equation", thieleEquation];
GoldRecord["regressions", regressions];
GoldRecord["all_regressions", And @@ Values[regressions]];

WriteString[$Output, "SPINTEXTURE_AGENT_RESULT_JSON_BEGIN\n"];
WriteString[$Output, ExportString[goldResults, "JSON"] <> "\n"];
WriteString[$Output, "SPINTEXTURE_AGENT_RESULT_JSON_END\n"];
Exit[0];
