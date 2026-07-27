(* ::Package:: *)
BeginPackage["SpinTextureTheory`"];

ExchangeDensity::usage = "ExchangeDensity[field, coords, A] returns A/2 Sum_i |partial_i field|^2.";
EasyAxisDensity::usage = "EasyAxisDensity[field, K, axisIndex] returns K/2 (1 - field_axis^2).";
InterfacialDMIDensity::usage = "InterfacialDMIDensity[field, coords, dCoeff, axisIndex] returns interfacial DMI density.";
BulkDMIDensity::usage = "BulkDMIDensity[field, coords3D, dCoeff] returns dCoeff field . Curl[field, coords3D].";
AnisotropicDMIDensity::usage = "AnisotropicDMIDensity[field, {x,y}, dCoeff, axisIndex] returns the opposite-sign x/y DMI density used for antiskyrmion-like textures.";
EulerLagrangeScalar::usage = "EulerLagrangeScalar[density, field, coords] gives variational derivative.";
EulerLagrangeVector::usage = "EulerLagrangeVector[density, fields, coords] gives vector variational derivative.";
AFMSigmaEquation::usage = "AFMSigmaEquation[n, w, coords, t, chi, alpha, s, drive] gives n x [chi n_tt + alpha s n_t + deltaU/deltan - drive].";
SOTDrive::usage = "SOTDrive[field, p, tauDL, tauFL] gives tauDL field x (field x p) + tauFL field x p.";
DomainWallAnsatz::usage = "DomainWallAnsatz[x,t,X,Phi,Delta,polarity] gives a normalized 1D domain wall ansatz; polarity defaults to 1.";
SkyrmionAnsatz::usage = "SkyrmionAnsatz[x,y,X,Y,R0,Delta,polarity,winding,helicity] gives a normalized radial skyrmion ansatz.";
AxisymmetricSkyrmionField::usage = "AxisymmetricSkyrmionField[theta,phi,polarity,winding,helicity] gives an axisymmetric unit-vector field for a symbolic radial profile theta.";
PolarTranslationTangents::usage = "PolarTranslationTangents[field,r,phi] gives the X and Y rigid-translation tangents in polar coordinates.";
ScaledPolarSpatialDerivatives::usage = "ScaledPolarSpatialDerivatives[field,r,phi,lambdaX,lambdaY] gives physical x/y derivatives for x=lambdaX r cos(phi), y=lambdaY r sin(phi).";
AngularCollectiveGyrotropicTensor::usage = "AngularCollectiveGyrotropicTensor[field,tangents,r,phi,prefactor,assumptions] integrates the gyrotropic projection over the polar angle, retaining the radial density.";
AngularCollectiveMetricMatrix::usage = "AngularCollectiveMetricMatrix[tangents,r,phi,assumptions] integrates the collective metric over the polar angle, retaining the radial density.";
AngularLLGTorqueGeneralizedForce::usage = "AngularLLGTorqueGeneralizedForce[field,tangents,torque,r,phi,prefactor,assumptions] projects an LLG torque using torque.(field cross tangent) and integrates over the polar angle.";
AngularGeneralizedForceDensity::usage = "AngularGeneralizedForceDensity[tangents,force,r,phi,assumptions] projects a force density using force.partial_q field and integrates over the polar angle.";
RadialTopologicalDensity2D::usage = "RadialTopologicalDensity2D[theta,r,winding,polarity] gives polarity winding Sin[theta] theta_r/(4 Pi r) for an axisymmetric texture.";
ThieleGyrotropicTensor::usage = "ThieleGyrotropicTensor[Q,prefactor] gives the 2D gyrotropic tensor 4 Pi prefactor Q epsilon_ij.";
IsotropicCollectiveTensor::usage = "IsotropicCollectiveTensor[value] gives a 2D isotropic collective-coordinate tensor.";
DimensionProduct::usage = "DimensionProduct[v1,v2,...] adds base-dimension exponent vectors.";
DimensionQuotient::usage = "DimensionQuotient[v1,v2] subtracts base-dimension exponent vectors.";
DimensionPower::usage = "DimensionPower[v,p] multiplies a base-dimension exponent vector by p.";
DimensionEqualQ::usage = "DimensionEqualQ[v1,v2,...] checks that base-dimension exponent vectors are identical.";
CollectiveMetricMatrix::usage = "CollectiveMetricMatrix[field,qList,ranges,assumptions] computes the integrated collective-coordinate metric.";
CollectiveMassMatrix::usage = "CollectiveMassMatrix[field,qList,ranges,chi,assumptions] computes M_ij from the collective metric.";
CollectiveDampingMatrix::usage = "CollectiveDampingMatrix[field,qList,ranges,alpha,s,assumptions] computes Gamma_ij from the collective metric.";
CollectiveGyrotropicTensor::usage = "CollectiveGyrotropicTensor[field, qList, ranges, prefactor] computes the gyrotropic tensor from field . (dq_i field x dq_j field).";
GeneralizedForce::usage = "GeneralizedForce[field,qList,force,ranges,assumptions] computes generalized forces.";
DomainWallSOTGeneralizedForce::usage = "DomainWallSOTGeneralizedForce[phi,Delta,polarity,p,tauDL,tauFL] integrates the X and Phi generalized forces for the standard wall ansatz.";
TopologicalDensity2D::usage = "TopologicalDensity2D[field, x, y] returns field . (field_x cross field_y)/(4 Pi).";
TopologicalCharge2D::usage = "TopologicalCharge2D[field, {x,xmin,xmax}, {y,ymin,ymax}] integrates topological density.";
AxisymmetricTopologicalChargeFromBoundaries::usage = "AxisymmetricTopologicalChargeFromBoundaries[thetaCore,thetaFar,winding,polarity] evaluates the axisymmetric charge from radial polar-angle boundaries.";
CompositeMeronTopologicalCharge::usage = "CompositeMeronTopologicalCharge[polarities,windings] sums the boundary-conditioned half charges polarity_i winding_i/2 of meron constituents.";
WindingNumberFromPhase::usage = "WindingNumberFromPhase[phase,phi] integrates d phase/d phi around a closed 2 Pi contour.";
StabilityMatrix::usage = "StabilityMatrix[Ueff, qList, equilibriumRules] returns Hessian at equilibrium.";
LinearStabilityMatrix::usage = "LinearStabilityMatrix[Ueff, qList, equilibriumRules] is an alias for the collective-coordinate Hessian.";
EigenFrequencyEquation::usage = "EigenFrequencyEquation[M, Gamma, K, omega] returns Det[-omega^2 M - I omega Gamma + K] == 0.";

Begin["`Private`"];

ExchangeDensity[field_List, coords_List, A_] := Simplify[
  A/2 Sum[D[field, coords[[i]]] . D[field, coords[[i]]], {i, Length[coords]}]
];

EasyAxisDensity[field_List, K_, axisIndex_Integer] := Simplify[
  K/2 (1 - field[[axisIndex]]^2)
];

InterfacialDMIDensity[field_List, coords_List, dCoeff_, axisIndex_Integer] := Module[
  {normalComponent, divField, gradNormal},
  normalComponent = field[[axisIndex]];
  divField = Sum[D[field[[i]], coords[[i]]], {i, Min[Length[coords], Length[field]]}];
  gradNormal = Table[D[normalComponent, coords[[i]]], {i, Length[coords]}];
  Simplify[dCoeff (normalComponent divField - Take[field, Length[coords]] . gradNormal)]
];

BulkDMIDensity[field_List, coords_List, dCoeff_] := Simplify[
  dCoeff field . Curl[field, coords]
];

AnisotropicDMIDensity[
  field_List, coords : {_, _}, dCoeff_, axisIndex_Integer
] := Module[
  {xCoord, yCoord, normalComponent, xComponent, yComponent},
  {xCoord, yCoord} = coords;
  normalComponent = field[[axisIndex]];
  xComponent = field[[1]];
  yComponent = field[[2]];
  Simplify[
    dCoeff (
      normalComponent D[xComponent, xCoord] - xComponent D[normalComponent, xCoord]
      - normalComponent D[yComponent, yCoord] + yComponent D[normalComponent, yCoord]
    )
  ]
];

EulerLagrangeScalar[density_, field_, coords_List] := Simplify[
  D[density, field] - Sum[D[D[density, D[field, coords[[i]]]], coords[[i]]], {i, Length[coords]}]
];

EulerLagrangeVector[density_, fields_List, coords_List] := Simplify[
  Table[EulerLagrangeScalar[density, fields[[i]], coords], {i, Length[fields]}]
];

SOTDrive[field_List, p_List, tauDL_, tauFL_] := Simplify[
  tauDL Cross[field, Cross[field, p]] + tauFL Cross[field, p]
];

AFMSigmaEquation[nVec_List, energyDensity_, coords_List, t_, chi_, alpha_, s_, drive_List] := Module[
  {varDeriv, nDot, nDDot},
  varDeriv = EulerLagrangeVector[energyDensity, nVec, coords];
  nDot = D[nVec, t];
  nDDot = D[nVec, {t, 2}];
  Simplify[Cross[nVec, chi nDDot + alpha s nDot + varDeriv - drive]]
];

DomainWallAnsatz[
  x_, t_, X_Symbol, Phi_Symbol, Delta_Symbol, polarity_: 1
] := Module[
  {theta, phi},
  theta = 2 ArcTan[Exp[(x - X[t])/Delta]];
  phi = Phi[t];
  Simplify[{Sin[theta] Cos[phi], Sin[theta] Sin[phi], polarity Cos[theta]}]
];

SkyrmionAnsatz[
  x_, y_, X_, Y_, R0_, Delta_, polarity_: 1, winding_: 1, helicity_: 0
] := Module[
  {rho, phi, theta},
  rho = Sqrt[(x - X)^2 + (y - Y)^2];
  phi = ArcTan[x - X, y - Y];
  theta = 2 ArcTan[Exp[(R0 - rho)/Delta]];
  Simplify[
    {
      Sin[theta] Cos[winding phi + helicity],
      Sin[theta] Sin[winding phi + helicity],
      polarity Cos[theta]
    }
  ]
];

AxisymmetricSkyrmionField[
  theta_, phi_, polarity_: 1, winding_: 1, helicity_: 0
] := Simplify[
  {
    Sin[theta] Cos[winding phi + helicity],
    Sin[theta] Sin[winding phi + helicity],
    polarity Cos[theta]
  }
];

PolarTranslationTangents[field_List, r_, phi_] := Module[
  {radialDerivative, angularDerivative},
  radialDerivative = D[field, r];
  angularDerivative = D[field, phi];
  Simplify[
    {
      -(Cos[phi] radialDerivative - Sin[phi] angularDerivative/r),
      -(Sin[phi] radialDerivative + Cos[phi] angularDerivative/r)
    }
  ]
];

ScaledPolarSpatialDerivatives[
  field_List, r_, phi_, lambdaX_, lambdaY_
] := Module[
  {radialDerivative, angularDerivative},
  radialDerivative = D[field, r];
  angularDerivative = D[field, phi];
  Simplify[
    {
      (Cos[phi] radialDerivative - Sin[phi] angularDerivative/r)/lambdaX,
      (Sin[phi] radialDerivative + Cos[phi] angularDerivative/r)/lambdaY
    }
  ]
];

AngularCollectiveGyrotropicTensor[
  field_List, tangents_List, r_, phi_, prefactor_: 1, assumptions_: True
] := FullSimplify[
  prefactor Integrate[
    r Table[
      field . Cross[tangents[[i]], tangents[[j]]],
      {i, Length[tangents]}, {j, Length[tangents]}
    ],
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];

AngularCollectiveMetricMatrix[
  tangents_List, r_, phi_, assumptions_: True
] := FullSimplify[
  Integrate[
    r Table[
      tangents[[i]] . tangents[[j]],
      {i, Length[tangents]}, {j, Length[tangents]}
    ],
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];

AngularLLGTorqueGeneralizedForce[
  field_List, tangents_List, torque_List, r_, phi_, prefactor_: 1,
  assumptions_: True
] := FullSimplify[
  prefactor Integrate[
    r Table[
      torque . Cross[field, tangents[[i]]],
      {i, Length[tangents]}
    ],
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];

AngularGeneralizedForceDensity[
  tangents_List, force_List, r_, phi_, assumptions_: True
] := FullSimplify[
  Integrate[
    r Table[
      force . tangents[[i]],
      {i, Length[tangents]}
    ],
    {phi, 0, 2 Pi},
    Assumptions -> assumptions,
    GenerateConditions -> False
  ],
  assumptions
];

RadialTopologicalDensity2D[theta_, r_, winding_: 1, polarity_: 1] := Simplify[
  polarity winding Sin[theta] D[theta, r]/(4 Pi r)
];

ThieleGyrotropicTensor[Q_, prefactor_: 1] := Simplify[
  {{0, -4 Pi prefactor Q}, {4 Pi prefactor Q, 0}}
];

IsotropicCollectiveTensor[value_] := {{value, 0}, {0, value}};

DimensionProduct[vectors__List] := Total[{vectors}];

DimensionQuotient[numerator_List, denominator_List] := numerator - denominator;

DimensionPower[vector_List, power_] := power vector;

DimensionEqualQ[vectors__List] := SameQ @@ {vectors};

CollectiveMetricMatrix[
  field_List, qList_List, ranges_List, assumptions_: True
] := FullSimplify[
  Table[
    Integrate[
      D[field, qList[[i]]] . D[field, qList[[j]]],
      Sequence @@ ranges,
      Assumptions -> assumptions,
      GenerateConditions -> False
    ],
    {i, Length[qList]}, {j, Length[qList]}
  ],
  assumptions
];

CollectiveMassMatrix[
  field_List, qList_List, ranges_List, chi_, assumptions_: True
] := FullSimplify[
  chi CollectiveMetricMatrix[field, qList, ranges, assumptions],
  assumptions
];

CollectiveDampingMatrix[
  field_List, qList_List, ranges_List, alpha_, s_, assumptions_: True
] := FullSimplify[
  alpha s CollectiveMetricMatrix[field, qList, ranges, assumptions],
  assumptions
];

CollectiveGyrotropicTensor[field_List, qList_List, ranges_List, prefactor_: 1] := Simplify[
  Table[
    prefactor Integrate[field . Cross[D[field, qList[[i]]], D[field, qList[[j]]]], Sequence @@ ranges],
    {i, Length[qList]}, {j, Length[qList]}
  ]
];

GeneralizedForce[
  field_List, qList_List, force_List, ranges_List, assumptions_: True
] := FullSimplify[
  Table[
    Integrate[
      force . D[field, qList[[i]]],
      Sequence @@ ranges,
      Assumptions -> assumptions,
      GenerateConditions -> False
    ],
    {i, Length[qList]}
  ],
  assumptions
];

DomainWallSOTGeneralizedForce[
  phi_, delta_, polarity_, p_List, tauDL_, tauFL_
] := Module[
  {xi, nXi, forceXi, tangentX, tangentPhi, integrands, assumptions},
  assumptions = delta > 0 && polarity^2 == 1 &&
    Element[Flatten[{phi, p, tauDL, tauFL, polarity}], Reals];
  nXi = {Sech[xi] Cos[phi], Sech[xi] Sin[phi], -polarity Tanh[xi]};
  forceXi = SOTDrive[nXi, p, tauDL, tauFL];
  tangentX = -(1/delta) D[nXi, xi];
  tangentPhi = D[nXi, phi];
  integrands = FullSimplify[delta {forceXi . tangentX, forceXi . tangentPhi}, assumptions];
  FullSimplify[
    Integrate[
      integrands,
      {xi, -Infinity, Infinity},
      Assumptions -> assumptions,
      GenerateConditions -> False
    ],
    assumptions
  ]
];

TopologicalDensity2D[field_List, x_, y_] := Simplify[
  field . Cross[D[field, x], D[field, y]]/(4 Pi)
];

TopologicalCharge2D[field_List, xRange_List, yRange_List] := Simplify[
  Integrate[TopologicalDensity2D[field, xRange[[1]], yRange[[1]]], xRange, yRange]
];

AxisymmetricTopologicalChargeFromBoundaries[
  thetaCore_, thetaFar_, winding_, polarity_: 1
] := FullSimplify[
  polarity winding/2 Integrate[Sin[u], {u, thetaCore, thetaFar}]
];

CompositeMeronTopologicalCharge[polarities_List, windings_List] := If[
  Length[polarities] == Length[windings],
  FullSimplify[Total[MapThread[#1 #2/2 &, {polarities, windings}]]],
  $Failed
];

WindingNumberFromPhase[phase_, phi_] := FullSimplify[
  Integrate[D[phase, phi], {phi, 0, 2 Pi}]/(2 Pi)
];

StabilityMatrix[Ueff_, qList_List, equilibriumRules_List] := Simplify[
  Table[D[Ueff, qList[[i]], qList[[j]]] /. equilibriumRules, {i, Length[qList]}, {j, Length[qList]}]
];

LinearStabilityMatrix[Ueff_, qList_List, equilibriumRules_List] := StabilityMatrix[
  Ueff, qList, equilibriumRules
];

EigenFrequencyEquation[M_, Gamma_, Kmat_, omega_] := Simplify[
  Det[-omega^2 M - I omega Gamma + Kmat] == 0
];

End[];
EndPackage[];
