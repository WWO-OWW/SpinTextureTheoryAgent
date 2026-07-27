(* Independent analytic gold path for C2. Do not load the project package. *)
ClearAll["Global`*"];

ToGoldString[expr_String] := expr;
ToGoldString[expr_] := ToString[expr, InputForm];
goldResults = <||>;
GoldRecord[key_String, expr_] := (
  goldResults = Join[goldResults, <|key -> ToGoldString[expr]|>];
  expr
);

ClearAll[
  r, phi, thetaProfile, uTheta, polarity, winding, helicity, pLit, wLit
];
assumptions = r > 0 && polarity^2 == 1 && winding^2 == 1 &&
  Element[{r, phi, polarity, winding, helicity}, Reals];

meronField = {
  Sin[thetaProfile[r]] Cos[winding phi + helicity],
  Sin[thetaProfile[r]] Sin[winding phi + helicity],
  polarity Cos[thetaProfile[r]]
};
radialDerivative = D[meronField, r];
angularDerivative = D[meronField, phi];

(* Direct Cartesian derivatives expressed in polar coordinates. *)
spatialX =
  Cos[phi] radialDerivative - Sin[phi] angularDerivative/r;
spatialY =
  Sin[phi] radialDerivative + Cos[phi] angularDerivative/r;
topologicalDensity = FullSimplify[
  meronField . Cross[spatialX, spatialY]/(4 Pi),
  assumptions
];
expectedTopologicalDensity =
  polarity winding Sin[thetaProfile[r]] thetaProfile'[r]/(4 Pi r);
radialChargeDensity = FullSimplify[
  Integrate[
    r topologicalDensity,
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
expectedRadialChargeDensity =
  polarity winding Sin[thetaProfile[r]] thetaProfile'[r]/2;

(* theta(0)=0 and theta(infinity)=Pi/2 define the registered meron. *)
topologicalCharge = FullSimplify[
  polarity winding/2 Integrate[
    Sin[uTheta],
    {uTheta, 0, Pi/2}
  ],
  polarity^2 == 1 && winding^2 == 1
];
literatureMeronSourceCharge = pLit wLit/2;
literatureMeronTransformedCharge = FullSimplify[
  literatureMeronSourceCharge /. {pLit -> polarity, wLit -> winding},
  assumptions
];
literatureMeronTargetCharge = topologicalCharge;
literatureMeronExactRegression = TrueQ[
  FullSimplify[
    literatureMeronTransformedCharge - literatureMeronTargetCharge,
    assumptions
  ] === 0
];
boundaryConditions = <|
  "theta_core" -> 0,
  "theta_far" -> Pi/2,
  "core_mz" -> polarity,
  "far_mz" -> 0,
  "winding_squared" -> 1
|>;
windingSignControl = FullSimplify[
  topologicalCharge /. winding -> -winding,
  polarity^2 == 1 && winding^2 == 1
];
polaritySignControl = FullSimplify[
  topologicalCharge /. polarity -> -polarity,
  polarity^2 == 1 && winding^2 == 1
];
nonMeronBoundaryControlCharge = FullSimplify[
  polarity winding/2 Integrate[Sin[uTheta], {uTheta, 0, 0}]
];

dimDensity = {-2};
dimArea = {2};
dimensionContract = <|
  "basis" -> {"length"},
  "convention" -> "dimensionless_topological_invariant",
  "topological_density" -> dimDensity,
  "area_element" -> dimArea,
  "charge" -> {0}
|>;

regressions = <|
  "unit_constraint" -> TrueQ[
    FullSimplify[meronField . meronField, assumptions] === 1
  ],
  "local_topological_density" -> TrueQ[
    FullSimplify[
      topologicalDensity - expectedTopologicalDensity,
      assumptions
    ] === 0
  ],
  "radial_charge_density" -> TrueQ[
    FullSimplify[
      radialChargeDensity - expectedRadialChargeDensity,
      assumptions
    ] === 0
  ],
  "boundary_charge" -> TrueQ[
    FullSimplify[
      topologicalCharge - polarity winding/2,
      assumptions
    ] === 0
  ],
  "half_charge_magnitude" -> TrueQ[
    FullSimplify[topologicalCharge^2, assumptions] === 1/4
  ],
  "winding_sign_control" -> TrueQ[
    FullSimplify[
      windingSignControl + topologicalCharge,
      assumptions
    ] === 0
  ],
  "polarity_sign_control" -> TrueQ[
    FullSimplify[
      polaritySignControl + topologicalCharge,
      assumptions
    ] === 0
  ],
  "non_meron_boundary_control" ->
    TrueQ[nonMeronBoundaryControlCharge === 0],
  "dimensionless_charge" ->
    TrueQ[dimDensity + dimArea === {0}]
|>;

GoldRecord["meron_ansatz", meronField];
GoldRecord[
  "ansatz_constraint_regression",
  regressions["unit_constraint"]
];
GoldRecord["topological_density", topologicalDensity];
GoldRecord["radial_charge_density", radialChargeDensity];
GoldRecord["boundary_conditions", boundaryConditions];
GoldRecord["topological_charge", topologicalCharge];
GoldRecord["literature_meron_source_charge", literatureMeronSourceCharge];
GoldRecord["literature_meron_transformed_charge", literatureMeronTransformedCharge];
GoldRecord["literature_meron_target_charge", literatureMeronTargetCharge];
GoldRecord["literature_meron_exact_regression", literatureMeronExactRegression];
GoldRecord[
  "boundary_charge_regression",
  regressions["boundary_charge"]
];
GoldRecord[
  "half_charge_magnitude_regression",
  regressions["half_charge_magnitude"]
];
GoldRecord[
  "winding_sign_regression",
  regressions["winding_sign_control"]
];
GoldRecord[
  "polarity_sign_regression",
  regressions["polarity_sign_control"]
];
GoldRecord[
  "non_meron_boundary_control_charge",
  nonMeronBoundaryControlCharge
];
GoldRecord[
  "non_meron_boundary_control_regression",
  regressions["non_meron_boundary_control"]
];
GoldRecord["dimension_contract", dimensionContract];
GoldRecord[
  "topology_dimension_regression",
  regressions["dimensionless_charge"]
];
GoldRecord["regressions", regressions];
GoldRecord["all_regressions", And @@ Values[regressions]];

WriteString[$Output, "SPINTEXTURE_AGENT_RESULT_JSON_BEGIN\n"];
WriteString[$Output, ExportString[goldResults, "JSON"] <> "\n"];
WriteString[$Output, "SPINTEXTURE_AGENT_RESULT_JSON_END\n"];
Exit[0];
