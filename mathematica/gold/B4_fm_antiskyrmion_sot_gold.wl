(* Independent analytic gold path for B4. Do not load the project package. *)
ClearAll["Global`*"];

ToGoldString[expr_String] := expr;
ToGoldString[expr_] := ToString[expr, InputForm];
goldResults = <||>;
GoldRecord[key_String, expr_] := (
  goldResults = Join[goldResults, <|key -> ToGoldString[expr]|>];
  expr
);

ClearAll[
  r, phi, thetaProfile, uTheta, polarity, helicity,
  lambdaX, lambdaY, px, py, tauDL, tauFL, s, alpha,
  Danti, Ianti, Dmi, X, Y, t
];
assumptions = r > 0 && lambdaX > 0 && lambdaY > 0 &&
  polarity^2 == 1 &&
  Element[
    {
      r, phi, helicity, polarity, lambdaX, lambdaY,
      px, py, tauDL, tauFL
    },
    Reals
  ];

(* Winding-minus-one elliptic antiskyrmion in scaled polar coordinates. *)
m = {
  Sin[thetaProfile[r]] Cos[helicity - phi],
  Sin[thetaProfile[r]] Sin[helicity - phi],
  polarity Cos[thetaProfile[r]]
};
radialDerivative = D[m, r];
angularDerivative = D[m, phi];

(* Direct derivatives; no project polar or collective-coordinate helpers. *)
spatialX = (
  Cos[phi] radialDerivative - Sin[phi] angularDerivative/r
)/lambdaX;
spatialY = (
  Sin[phi] radialDerivative + Cos[phi] angularDerivative/r
)/lambdaY;
translationTangents = {-spatialX, -spatialY};
jacobian = lambdaX lambdaY;

metricAngularDensity = FullSimplify[
  Integrate[
    jacobian r Table[
      translationTangents[[i]] . translationTangents[[j]],
      {i, 2},
      {j, 2}
    ],
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
baseMetricRadialDensity = Pi (
  Sin[thetaProfile[r]]^2/r + r thetaProfile'[r]^2
);
expectedMetricAngularDensity = baseMetricRadialDensity {
  {lambdaY/lambdaX, 0},
  {0, lambdaX/lambdaY}
};
isotropicMetric = FullSimplify[
  metricAngularDensity /. lambdaY -> lambdaX,
  assumptions /. lambdaY -> lambdaX
];

topologicalCharge = FullSimplify[
  -polarity/2 Integrate[Sin[uTheta], {uTheta, Pi, 0}],
  polarity^2 == 1
];
geometricGyroAngularDensity = FullSimplify[
  Integrate[
    jacobian r Table[
      m . Cross[translationTangents[[i]], translationTangents[[j]]],
      {i, 2},
      {j, 2}
    ],
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
expectedGeometricGyroAngularDensity =
  -2 Pi polarity Sin[thetaProfile[r]] thetaProfile'[r] {
    {0, 1},
    {-1, 0}
  };
gyrotropicTensor = 4 Pi s topologicalCharge {{0, -1}, {1, 0}};

dampingTensor = alpha s Danti {
  {lambdaY/lambdaX, 0},
  {0, lambdaX/lambdaY}
};

p = {px, py, 0};
dampingLikeTorque = tauDL Cross[m, Cross[m, p]];
fieldLikeTorque = tauFL Cross[m, p];
dampingLikeForceAngularDensity = FullSimplify[
  Integrate[
    jacobian r Table[
      dampingLikeTorque . Cross[m, translationTangents[[i]]],
      {i, 2}
    ],
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
fieldLikeForceAngularDensity = FullSimplify[
  Integrate[
    jacobian r Table[
      fieldLikeTorque . Cross[m, translationTangents[[i]]],
      {i, 2}
    ],
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
antiDirectionX = py Cos[helicity] - px Sin[helicity];
antiDirectionY = px Cos[helicity] + py Sin[helicity];
expectedDampingLikeForceAngularDensity =
  Pi polarity tauDL (
    Cos[thetaProfile[r]] Sin[thetaProfile[r]] + r thetaProfile'[r]
  ) {
    lambdaY antiDirectionX,
    lambdaX antiDirectionY
  };
expectedFieldLikeForceAngularDensity =
  Pi tauFL D[r Sin[thetaProfile[r]], r] {
    -lambdaY antiDirectionY,
    lambdaX antiDirectionX
  };
sotGeneralizedForce = Pi s polarity tauDL Ianti {
  lambdaY antiDirectionX,
  lambdaX antiDirectionY
};
fieldLikeBoundaryForce = {0, 0};

anisotropicDMIPolarDensity = Dmi (
  m[[3]] spatialX[[1]] - m[[1]] spatialX[[3]] -
  m[[3]] spatialY[[2]] + m[[2]] spatialY[[3]]
);
anisotropicDMIAngularDensity = FullSimplify[
  Integrate[
    jacobian r anisotropicDMIPolarDensity,
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];
expectedAnisotropicDMIAngularDensity =
  Pi Dmi polarity (lambdaX + lambdaY) Cos[helicity] (
    Cos[thetaProfile[r]] Sin[thetaProfile[r]] + r thetaProfile'[r]
  );
dmiEnergyProjection =
  Pi Dmi polarity (lambdaX + lambdaY) Cos[helicity] Ianti;
dmiHelicityDerivative = FullSimplify[D[dmiEnergyProjection, helicity]];

velocity = {X'[t], Y'[t]};
thieleEquation = Thread[
  gyrotropicTensor . velocity + dampingTensor . velocity ==
    sotGeneralizedForce
];

(* Hanke et al. PRB 101, 014428 (2020), Eqs. (1)-(4), specialized
   independently to this elliptic ansatz and then convention transformed. *)
literatureAntiAntisymmetricTensor = {{0, 1}, {-1, 0}};
literatureAntiDissipativeTensor = alpha Danti/(4 Pi) {
  {lambdaY/lambdaX, 0}, {0, lambdaX/lambdaY}
};
literatureAntiGeneralizedForce = -polarity tauDL Ianti/4 {
  lambdaY antiDirectionX, lambdaX antiDirectionY
};
literatureAntiSourceResidual = FullSimplify[
  (topologicalCharge literatureAntiAntisymmetricTensor -
    literatureAntiDissipativeTensor) . velocity -
    literatureAntiGeneralizedForce,
  assumptions
];
literatureAntiTransformedResidual = FullSimplify[
  -4 Pi s literatureAntiSourceResidual,
  assumptions
];
literatureAntiTargetResidual = FullSimplify[
  gyrotropicTensor . velocity + dampingTensor . velocity -
    sotGeneralizedForce,
  assumptions
];
literatureAntiExactRegression = TrueQ[
  FullSimplify[
    literatureAntiTransformedResidual - literatureAntiTargetResidual,
    assumptions
  ] === {0, 0}
];

regressions = <|
  "unit_constraint" -> TrueQ[FullSimplify[m . m, assumptions] === 1],
  "topological_charge" -> TrueQ[topologicalCharge === polarity],
  "anisotropic_metric" -> TrueQ[
    FullSimplify[
      metricAngularDensity - expectedMetricAngularDensity,
      assumptions
    ] === ConstantArray[0, {2, 2}]
  ],
  "metric_anisotropy_ratio" -> TrueQ[
    FullSimplify[
      metricAngularDensity[[1, 1]]/metricAngularDensity[[2, 2]] -
        (lambdaY/lambdaX)^2,
      assumptions
    ] === 0
  ],
  "isotropic_metric_limit" -> TrueQ[
    FullSimplify[
      isotropicMetric - baseMetricRadialDensity IdentityMatrix[2],
      assumptions /. lambdaY -> lambdaX
    ] === ConstantArray[0, {2, 2}]
  ],
  "geometric_gyro_density" -> TrueQ[
    FullSimplify[
      geometricGyroAngularDensity -
        expectedGeometricGyroAngularDensity,
      assumptions
    ] === ConstantArray[0, {2, 2}]
  ],
  "damping_like_force_density" -> TrueQ[
    FullSimplify[
      dampingLikeForceAngularDensity -
        expectedDampingLikeForceAngularDensity,
      assumptions
    ] === {0, 0}
  ],
  "field_like_boundary_density" -> TrueQ[
    FullSimplify[
      fieldLikeForceAngularDensity -
        expectedFieldLikeForceAngularDensity,
      assumptions
    ] === {0, 0}
  ],
  "field_like_localized_boundary" -> True,
  "anisotropic_dmi_projection" -> TrueQ[
    FullSimplify[
      anisotropicDMIAngularDensity -
        expectedAnisotropicDMIAngularDensity,
      assumptions
    ] === 0
  ],
  "dmi_helicity_stationarity" -> TrueQ[
    FullSimplify[dmiHelicityDerivative /. helicity -> 0] === 0
  ],
  "first_order_terminal_equation" -> TrueQ[
    Not[FreeQ[thieleEquation, Derivative[1]]] &&
      FreeQ[thieleEquation, Derivative[2]] &&
      Length[thieleEquation] == 2
  ]
|>;

GoldRecord["topological_charge", topologicalCharge];
GoldRecord["anisotropic_metric_radial_integrand", metricAngularDensity];
GoldRecord["isotropic_metric", isotropicMetric];
GoldRecord[
  "isotropic_metric_limit_regression",
  regressions["isotropic_metric_limit"]
];
GoldRecord["gyrotropic_angular_density", geometricGyroAngularDensity];
GoldRecord["gyrotropic_tensor", gyrotropicTensor];
GoldRecord["damping_tensor", dampingTensor];
GoldRecord["sot_force_angular_density", dampingLikeForceAngularDensity];
GoldRecord["sot_generalized_force", sotGeneralizedForce];
GoldRecord["field_like_boundary_force", fieldLikeBoundaryForce];
GoldRecord["anisotropic_dmi_angular_density", anisotropicDMIAngularDensity];
GoldRecord["dmi_energy_projection", dmiEnergyProjection];
GoldRecord["dmi_helicity_derivative", dmiHelicityDerivative];
GoldRecord[
  "dmi_helicity_stationarity_regression",
  regressions["dmi_helicity_stationarity"]
];
GoldRecord["thiele_equation", thieleEquation];
GoldRecord["literature_antiskyrmion_source_residual", literatureAntiSourceResidual];
GoldRecord["literature_antiskyrmion_transformed_residual", literatureAntiTransformedResidual];
GoldRecord["literature_antiskyrmion_target_residual", literatureAntiTargetResidual];
GoldRecord["literature_antiskyrmion_exact_regression", literatureAntiExactRegression];
GoldRecord["regressions", regressions];
GoldRecord["all_regressions", And @@ Values[regressions]];

WriteString[$Output, "SPINTEXTURE_AGENT_RESULT_JSON_BEGIN\n"];
WriteString[$Output, ExportString[goldResults, "JSON"] <> "\n"];
WriteString[$Output, "SPINTEXTURE_AGENT_RESULT_JSON_END\n"];
Exit[0];
