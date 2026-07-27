(* Independent analytic gold path for A4. Do not load SpinTextureTheory.wl. *)
ClearAll["Global`*"];

ToGoldString[expr_String] := expr;
ToGoldString[expr_] := ToString[expr, InputForm];
goldResults = <||>;
GoldRecord[key_String, expr_] := (
  goldResults = Join[goldResults, <|key -> ToGoldString[expr]|>];
  expr
);

ClearAll[
  xi, Delta, Phic, wallPolarity, px, py, pz, tauDL, tauFL,
  chi, alpha, s, k, u1, u2, u3, u4
];
assumptions = Delta > 0 && wallPolarity^2 == 1 &&
  Element[{Delta, Phic, wallPolarity, px, py, pz, tauDL, tauFL}, Reals];

(* Direct wall profile and collective tangents. *)
nWall = {
  Sech[xi] Cos[Phic],
  Sech[xi] Sin[Phic],
  -wallPolarity Tanh[xi]
};
tangentX = -(1/Delta) D[nWall, xi];
tangentPhi = D[nWall, Phic];
tangents = {tangentX, tangentPhi};
metricIntegrand = FullSimplify[
  Delta Table[tangents[[i]] . tangents[[j]], {i, 2}, {j, 2}],
  assumptions
];
metricMatrix = FullSimplify[
  Integrate[
    metricIntegrand,
    {xi, -Infinity, Infinity},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
expectedMetric = {{2/Delta, 0}, {0, 2 Delta}};
massMatrix = FullSimplify[chi metricMatrix, assumptions];
dampingMatrix = FullSimplify[alpha s metricMatrix, assumptions];

(* Direct sigma-model force-density projection. *)
p = {px, py, pz};
sotDensity = tauDL Cross[nWall, Cross[nWall, p]] + tauFL Cross[nWall, p];
sotIntegrand = FullSimplify[
  Delta {sotDensity . tangentX, sotDensity . tangentPhi},
  assumptions
];
sotForce = FullSimplify[
  Integrate[
    sotIntegrand,
    {xi, -Infinity, Infinity},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
expectedSOTForce = {
  wallPolarity (-2 pz tauDL + Pi py tauFL Cos[Phic] - Pi px tauFL Sin[Phic]),
  Delta (-2 pz tauFL - Pi py tauDL Cos[Phic] + Pi px tauDL Sin[Phic])
};

(* Periodic four-wall Hessian, calculated without the package helper. *)
u = {u1, u2, u3, u4};
wallEnergy = k/2 Sum[(u[[Mod[i, 4] + 1]] - u[[i]])^2, {i, 1, 4}];
stabilityMatrix = FullSimplify[Table[D[wallEnergy, u[[i]], u[[j]]], {i, 4}, {j, 4}]];
expectedStability = k {
  {2, -1, 0, -1},
  {-1, 2, -1, 0},
  {0, -1, 2, -1},
  {-1, 0, -1, 2}
};

metricBoundaryVanish = TrueQ[
  Join[
    Flatten[Limit[metricIntegrand, xi -> Infinity]],
    Flatten[Limit[metricIntegrand, xi -> -Infinity]]
  ] === ConstantArray[0, 8]
];
sotBoundaryVanish = TrueQ[
  Join[
    Limit[sotIntegrand, xi -> Infinity],
    Limit[sotIntegrand, xi -> -Infinity]
  ] === {0, 0, 0, 0}
];

regressions = <|
  "unit_constraint" -> TrueQ[FullSimplify[nWall . nWall, assumptions] === 1],
  "metric" -> TrueQ[FullSimplify[metricMatrix - expectedMetric, assumptions] === ConstantArray[0, {2, 2}]],
  "mass" -> TrueQ[FullSimplify[massMatrix - chi expectedMetric, assumptions] === ConstantArray[0, {2, 2}]],
  "damping" -> TrueQ[FullSimplify[dampingMatrix - alpha s expectedMetric, assumptions] === ConstantArray[0, {2, 2}]],
  "sot_force" -> TrueQ[FullSimplify[sotForce - expectedSOTForce, assumptions] === {0, 0}],
  "stability" -> TrueQ[FullSimplify[stabilityMatrix - expectedStability] === ConstantArray[0, {4, 4}]],
  "metric_boundary" -> metricBoundaryVanish,
  "sot_boundary" -> sotBoundaryVanish
|>;

GoldRecord["metric_matrix", metricMatrix];
GoldRecord["mass_matrix", massMatrix];
GoldRecord["damping_matrix", dampingMatrix];
GoldRecord["sot_generalized_force", sotForce];
GoldRecord["stability_matrix", stabilityMatrix];
GoldRecord["metric_boundary_vanish", metricBoundaryVanish];
GoldRecord["sot_boundary_vanish", sotBoundaryVanish];
GoldRecord["regressions", regressions];
GoldRecord["all_regressions", And @@ Values[regressions]];

WriteString[$Output, "SPINTEXTURE_AGENT_RESULT_JSON_BEGIN\n"];
WriteString[$Output, ExportString[goldResults, "JSON"] <> "\n"];
WriteString[$Output, "SPINTEXTURE_AGENT_RESULT_JSON_END\n"];
Exit[0];
