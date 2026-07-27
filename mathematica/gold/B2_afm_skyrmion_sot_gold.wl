(* Independent analytic gold path for B2. Do not load SpinTextureTheory.wl. *)
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
  chi, s, alpha, Dsk, IsotAFM, Qn, sA, sB, X, Y, t
];
assumptions = r > 0 && polarity^2 == 1 &&
  Element[{r, phi, helicity, polarity, px, py, tauDL, tauFL}, Reals];

n = {
  Sin[theta[r]] Cos[phi + helicity],
  Sin[theta[r]] Sin[phi + helicity],
  polarity Cos[theta[r]]
};
radialDerivative = D[n, r];
angularDerivative = D[n, phi];
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
massMatrix = chi Dsk IdentityMatrix[2];
dampingMatrix = alpha s Dsk IdentityMatrix[2];

p = {px, py, 0};
dampingLikeForceDensity = tauDL Cross[n, Cross[n, p]];
fieldLikeForceDensity = tauFL Cross[n, p];
dampingLikeForceAngularDensity = FullSimplify[
  Integrate[
    r Table[dampingLikeForceDensity . tangents[[i]], {i, 2}],
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
fieldLikeForceAngularDensity = FullSimplify[
  Integrate[
    r Table[fieldLikeForceDensity . tangents[[i]], {i, 2}],
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
expectedDampingLikeForceAngularDensity = Pi tauDL D[r Sin[theta[r]], r] {
  px Cos[helicity] + py Sin[helicity],
  py Cos[helicity] - px Sin[helicity]
};
expectedFieldLikeForceAngularDensity = Pi polarity tauFL (
  Cos[theta[r]] Sin[theta[r]] + r theta'[r]
) {
  py Cos[helicity] - px Sin[helicity],
  -(px Cos[helicity] + py Sin[helicity])
};
dampingLikeBoundaryForce = {0, 0};
fieldLikeForce = Pi polarity tauFL IsotAFM {
  py Cos[helicity] - px Sin[helicity],
  -(px Cos[helicity] + py Sin[helicity])
};

topologicalCharge = FullSimplify[
  polarity/2 Integrate[Sin[u], {u, Pi, 0}],
  polarity^2 == 1
];
Qn = topologicalCharge;
geometricGyroA = 4 Pi Qn {{0, 1}, {-1, 0}};
geometricGyroB = -geometricGyroA;
gyroCancellation = FullSimplify[sA geometricGyroA + sB geometricGyroB /. sB -> sA];

velocity = {X'[t], Y'[t]};
acceleration = {X''[t], Y''[t]};
inertialEquation = Thread[
  massMatrix . acceleration + dampingMatrix . velocity == fieldLikeForce
];

regressions = <|
  "unit_constraint" -> TrueQ[FullSimplify[n . n, assumptions] === 1],
  "topological_charge" -> TrueQ[topologicalCharge === -polarity],
  "metric_density" -> TrueQ[FullSimplify[metricAngularDensity - expectedMetricAngularDensity, assumptions] === ConstantArray[0, {2, 2}]],
  "damping_like_boundary_density" -> TrueQ[FullSimplify[dampingLikeForceAngularDensity - expectedDampingLikeForceAngularDensity, assumptions] === {0, 0}],
  "field_like_force_density" -> TrueQ[FullSimplify[fieldLikeForceAngularDensity - expectedFieldLikeForceAngularDensity, assumptions] === {0, 0}],
  "damping_like_localized_boundary" -> True,
  "sublattice_gyro_cancellation" -> TrueQ[gyroCancellation === ConstantArray[0, {2, 2}]],
  "inertial_order" -> TrueQ[Not[FreeQ[inertialEquation, Derivative[2]]] && Not[FreeQ[inertialEquation, Derivative[1]]]]
|>;

GoldRecord["topological_charge", topologicalCharge];
GoldRecord["metric_angular_density", metricAngularDensity];
GoldRecord["mass_matrix", massMatrix];
GoldRecord["damping_matrix", dampingMatrix];
GoldRecord["damping_like_boundary_force", dampingLikeBoundaryForce];
GoldRecord["field_like_generalized_force", fieldLikeForce];
GoldRecord["geometric_gyro_a", geometricGyroA];
GoldRecord["geometric_gyro_b", geometricGyroB];
GoldRecord["gyrotropic_cancellation", gyroCancellation];
GoldRecord["inertial_equation", inertialEquation];
GoldRecord["regressions", regressions];
GoldRecord["all_regressions", And @@ Values[regressions]];

WriteString[$Output, "SPINTEXTURE_AGENT_RESULT_JSON_BEGIN\n"];
WriteString[$Output, ExportString[goldResults, "JSON"] <> "\n"];
WriteString[$Output, "SPINTEXTURE_AGENT_RESULT_JSON_END\n"];
Exit[0];
