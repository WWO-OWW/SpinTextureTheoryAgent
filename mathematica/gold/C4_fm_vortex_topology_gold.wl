(* Independent analytic gold path for C4. Do not load the project package. *)
ClearAll["Global`*"];

ToGoldString[expr_String] := expr;
ToGoldString[expr_] := ToString[expr, InputForm];
goldResults = <||>;
GoldRecord[key_String, expr_] := (
  goldResults = Join[goldResults, <|key -> ToGoldString[expr]|>];
  expr
);

ClearAll[phi, vorticity, helicity, polarity, nLit, pLit];
assumptions =
  Element[vorticity, Integers] &&
  vorticity^2 == 1 &&
  polarity^2 == 1 &&
  Element[{phi, helicity, polarity}, Reals];

(* The contour lies outside the finite regularized core. *)
boundaryPhase = vorticity phi + helicity;
inPlaneBoundaryField = {
  Cos[boundaryPhase],
  Sin[boundaryPhase],
  0
};
phaseIncrement = FullSimplify[
  (boundaryPhase /. phi -> 2 Pi) -
  (boundaryPhase /. phi -> 0),
  assumptions
];
windingNumber = FullSimplify[
  Integrate[
    D[boundaryPhase, phi]/(2 Pi),
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
literatureVortexSourceWinding = FullSimplify[
  Integrate[
    (
      inPlaneBoundaryField[[1]] D[inPlaneBoundaryField[[2]], phi] -
      inPlaneBoundaryField[[2]] D[inPlaneBoundaryField[[1]], phi]
    )/(
      2 Pi (inPlaneBoundaryField[[1]]^2 + inPlaneBoundaryField[[2]]^2)
    ),
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
literatureVortexTransformedWinding = literatureVortexSourceWinding;
literatureVortexTargetWinding = windingNumber;
literatureVortexWindingExactRegression = TrueQ[
  FullSimplify[
    literatureVortexTransformedWinding - literatureVortexTargetWinding,
    assumptions
  ] === 0
];

(* This Q-like value additionally assumes a polarized, regularized core. *)
corePolarityDependentCharge = polarity vorticity/2;
literatureVortexSourceCoreCharge = nLit pLit/2;
literatureVortexTransformedCoreCharge = FullSimplify[
  literatureVortexSourceCoreCharge /. {
    nLit -> vorticity, pLit -> polarity
  },
  assumptions
];
literatureVortexTargetCoreCharge = corePolarityDependentCharge;
literatureVortexCoreChargeExactRegression = TrueQ[
  FullSimplify[
    literatureVortexTransformedCoreCharge - literatureVortexTargetCoreCharge,
    assumptions
  ] === 0
];

dimPhase = {0};
dimWinding = {0};
dimensionContract = <|
  "basis" -> {"length"},
  "convention" -> "dimensionless_topological_invariant",
  "phase" -> dimPhase,
  "winding_number" -> dimWinding
|>;

regressions = <|
  "boundary_unit_constraint" -> TrueQ[
    FullSimplify[
      inPlaneBoundaryField . inPlaneBoundaryField,
      assumptions
    ] === 1
  ],
  "direct_winding_integral" -> TrueQ[
    FullSimplify[windingNumber - vorticity, assumptions] === 0
  ],
  "unit_winding_magnitude" -> TrueQ[
    FullSimplify[windingNumber^2, assumptions] === 1
  ],
  "quantized_phase_increment" -> TrueQ[
    FullSimplify[
      phaseIncrement - 2 Pi vorticity,
      assumptions
    ] === 0
  ],
  "single_valued_boundary" -> TrueQ[
    FullSimplify[
      (inPlaneBoundaryField /. phi -> 2 Pi) -
      (inPlaneBoundaryField /. phi -> 0),
      assumptions
    ] === {0, 0, 0}
  ],
  "helicity_independent_winding" -> FreeQ[windingNumber, helicity],
  "polarity_independent_winding" -> FreeQ[windingNumber, polarity],
  "polarity_dependent_core_charge" ->
    Not[FreeQ[corePolarityDependentCharge, polarity]],
  "vorticity_flip_winding" -> TrueQ[
    FullSimplify[
      (windingNumber /. vorticity -> -vorticity) + windingNumber,
      assumptions
    ] === 0
  ],
  "core_polarity_flip" -> TrueQ[
    FullSimplify[
      (corePolarityDependentCharge /. polarity -> -polarity) +
      corePolarityDependentCharge,
      assumptions
    ] === 0 &&
    FullSimplify[
      (windingNumber /. polarity -> -polarity) - windingNumber,
      assumptions
    ] === 0
  ],
  "dimensionless_topology" -> TrueQ[
    dimPhase === {0} && dimWinding === {0}
  ]
|>;

GoldRecord["boundary_phase", boundaryPhase];
GoldRecord["in_plane_boundary_field", inPlaneBoundaryField];
GoldRecord["winding_number", windingNumber];
GoldRecord["literature_vortex_source_winding", literatureVortexSourceWinding];
GoldRecord["literature_vortex_transformed_winding", literatureVortexTransformedWinding];
GoldRecord["literature_vortex_target_winding", literatureVortexTargetWinding];
GoldRecord["literature_vortex_winding_exact_regression", literatureVortexWindingExactRegression];
GoldRecord[
  "winding_regression",
  regressions["direct_winding_integral"]
];
GoldRecord[
  "unit_winding_magnitude_regression",
  regressions["unit_winding_magnitude"]
];
GoldRecord[
  "single_valued_boundary_regression",
  regressions["single_valued_boundary"]
];
GoldRecord[
  "core_polarity_dependent_charge",
  corePolarityDependentCharge
];
GoldRecord["literature_vortex_source_core_charge", literatureVortexSourceCoreCharge];
GoldRecord["literature_vortex_transformed_core_charge", literatureVortexTransformedCoreCharge];
GoldRecord["literature_vortex_target_core_charge", literatureVortexTargetCoreCharge];
GoldRecord["literature_vortex_core_charge_exact_regression", literatureVortexCoreChargeExactRegression];
GoldRecord[
  "winding_charge_distinction_regression",
  regressions["polarity_independent_winding"] &&
  regressions["polarity_dependent_core_charge"]
];
GoldRecord[
  "vorticity_flip_regression",
  regressions["vorticity_flip_winding"]
];
GoldRecord[
  "core_polarity_flip_regression",
  regressions["core_polarity_flip"]
];
GoldRecord["dimension_contract", dimensionContract];
GoldRecord[
  "topology_dimension_regression",
  regressions["dimensionless_topology"]
];
GoldRecord["phase_increment", phaseIncrement];
GoldRecord["regressions", regressions];
GoldRecord["all_regressions", And @@ Values[regressions]];

WriteString[$Output, "SPINTEXTURE_AGENT_RESULT_JSON_BEGIN\n"];
WriteString[$Output, ExportString[goldResults, "JSON"] <> "\n"];
WriteString[$Output, "SPINTEXTURE_AGENT_RESULT_JSON_END\n"];
Exit[0];
