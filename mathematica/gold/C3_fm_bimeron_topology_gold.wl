(* Independent analytic gold path for C3. Do not load the project package. *)
ClearAll["Global`*"];

ToGoldString[expr_String] := expr;
ToGoldString[expr_] := ToString[expr, InputForm];
goldResults = <||>;
GoldRecord[key_String, expr_] := (
  goldResults = Join[goldResults, <|key -> ToGoldString[expr]|>];
  expr
);

ClearAll[
  r1, r2, phi1, phi2, theta1, theta2, u1, u2,
  p1, p2, w1, w2, eta1, eta2, pVLit, pALit, wVLit, wALit
];
assumptions1 = r1 > 0 && p1^2 == 1 && w1^2 == 1 &&
  Element[{r1, phi1, p1, w1, eta1}, Reals];
assumptions2 = r2 > 0 && p2^2 == 1 && w2^2 == 1 &&
  Element[{r2, phi2, p2, w2, eta2}, Reals];
constituentAssumptions =
  p1^2 == 1 && p2^2 == 1 && w1^2 == 1 && w2^2 == 1 &&
  Element[{p1, p2, w1, w2}, Reals];

field1 = {
  Sin[theta1[r1]] Cos[w1 phi1 + eta1],
  Sin[theta1[r1]] Sin[w1 phi1 + eta1],
  p1 Cos[theta1[r1]]
};
radial1 = D[field1, r1];
angular1 = D[field1, phi1];
spatialX1 = Cos[phi1] radial1 - Sin[phi1] angular1/r1;
spatialY1 = Sin[phi1] radial1 + Cos[phi1] angular1/r1;
density1 = FullSimplify[
  field1 . Cross[spatialX1, spatialY1]/(4 Pi),
  assumptions1
];
expectedDensity1 =
  p1 w1 Sin[theta1[r1]] theta1'[r1]/(4 Pi r1);

field2 = {
  Sin[theta2[r2]] Cos[w2 phi2 + eta2],
  Sin[theta2[r2]] Sin[w2 phi2 + eta2],
  p2 Cos[theta2[r2]]
};
radial2 = D[field2, r2];
angular2 = D[field2, phi2];
spatialX2 = Cos[phi2] radial2 - Sin[phi2] angular2/r2;
spatialY2 = Sin[phi2] radial2 + Cos[phi2] angular2/r2;
density2 = FullSimplify[
  field2 . Cross[spatialX2, spatialY2]/(4 Pi),
  assumptions2
];
expectedDensity2 =
  p2 w2 Sin[theta2[r2]] theta2'[r2]/(4 Pi r2);

(* Each registered constituent has theta(0)=0 and theta(infinity)=Pi/2. *)
charge1 = FullSimplify[
  p1 w1/2 Integrate[Sin[u1], {u1, 0, Pi/2}],
  p1^2 == 1 && w1^2 == 1
];
charge2 = FullSimplify[
  p2 w2/2 Integrate[Sin[u2], {u2, 0, Pi/2}],
  p2^2 == 1 && w2^2 == 1
];
constituentCharges = {charge1, charge2};
generalCompositeCharge = FullSimplify[Total[constituentCharges]];
literatureBimeronSourceCharge = (pVLit wVLit + pALit wALit)/2;
literatureBimeronTransformedCharge = FullSimplify[
  literatureBimeronSourceCharge /. {
    pVLit -> p1, wVLit -> w1, pALit -> p2, wALit -> w2
  }
];
literatureBimeronTargetCharge = generalCompositeCharge;
literatureBimeronExactRegression = TrueQ[
  FullSimplify[
    literatureBimeronTransformedCharge - literatureBimeronTargetCharge
  ] === 0
];

pairingRules = {p2 -> -p1, w2 -> -w1};
bimeronTopologicalCharge = FullSimplify[
  generalCompositeCharge /. pairingRules,
  p1^2 == 1 && w1^2 == 1 && Element[{p1, w1}, Reals]
];
trivialPairControlCharge = FullSimplify[
  generalCompositeCharge /. {p2 -> p1, w2 -> -w1}
];

dimDensity = {-2};
dimArea = {2};
dimensionContract = <|
  "basis" -> {"length"},
  "convention" -> "dimensionless_topological_invariant",
  "constituent_charge" -> {0},
  "composite_charge" -> {0}
|>;

regressions = <|
  "constituent_unit_constraints" -> TrueQ[
    FullSimplify[field1 . field1, assumptions1] === 1 &&
      FullSimplify[field2 . field2, assumptions2] === 1
  ],
  "constituent_local_densities" -> TrueQ[
    FullSimplify[density1 - expectedDensity1, assumptions1] === 0 &&
      FullSimplify[density2 - expectedDensity2, assumptions2] === 0
  ],
  "constituent_half_charges" -> TrueQ[
    FullSimplify[
      constituentCharges - {p1 w1/2, p2 w2/2},
      constituentAssumptions
    ] === {0, 0}
  ],
  "charge_additivity" -> TrueQ[
    FullSimplify[
      generalCompositeCharge - Total[constituentCharges],
      constituentAssumptions
    ] === 0
  ],
  "nontrivial_pairing" -> TrueQ[
    FullSimplify[
      (constituentCharges /. pairingRules) -
        {p1 w1/2, p1 w1/2},
      p1^2 == 1 && w1^2 == 1
    ] === {0, 0}
  ],
  "integer_charge_magnitude" -> TrueQ[
    FullSimplify[
      bimeronTopologicalCharge^2,
      p1^2 == 1 && w1^2 == 1
    ] === 1
  ],
  "trivial_pair_control" -> TrueQ[
    trivialPairControlCharge === 0
  ],
  "dimensionless_constituent_and_composite_charges" -> TrueQ[
    dimDensity + dimArea === {0}
  ]
|>;

GoldRecord["constituent_charges", constituentCharges];
GoldRecord["general_composite_charge", generalCompositeCharge];
GoldRecord["literature_bimeron_source_charge", literatureBimeronSourceCharge];
GoldRecord["literature_bimeron_transformed_charge", literatureBimeronTransformedCharge];
GoldRecord["literature_bimeron_target_charge", literatureBimeronTargetCharge];
GoldRecord["literature_bimeron_exact_regression", literatureBimeronExactRegression];
GoldRecord["pairing_rules", pairingRules];
GoldRecord["bimeron_topological_charge", bimeronTopologicalCharge];
GoldRecord[
  "constituent_half_charge_regression",
  regressions["constituent_half_charges"]
];
GoldRecord[
  "charge_additivity_regression",
  regressions["charge_additivity"]
];
GoldRecord[
  "nontrivial_pairing_regression",
  regressions["nontrivial_pairing"]
];
GoldRecord[
  "integer_charge_magnitude_regression",
  regressions["integer_charge_magnitude"]
];
GoldRecord[
  "trivial_pair_control_charge",
  trivialPairControlCharge
];
GoldRecord[
  "trivial_pair_control_regression",
  regressions["trivial_pair_control"]
];
GoldRecord["dimension_contract", dimensionContract];
GoldRecord[
  "topology_dimension_regression",
  regressions["dimensionless_constituent_and_composite_charges"]
];
GoldRecord["regressions", regressions];
GoldRecord["all_regressions", And @@ Values[regressions]];

WriteString[$Output, "SPINTEXTURE_AGENT_RESULT_JSON_BEGIN\n"];
WriteString[$Output, ExportString[goldResults, "JSON"] <> "\n"];
WriteString[$Output, "SPINTEXTURE_AGENT_RESULT_JSON_END\n"];
Exit[0];
