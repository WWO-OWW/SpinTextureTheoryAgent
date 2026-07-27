# Extended-route literature reproduction protocol

## Scope

This protocol covers the four full routes outside core three:

| Route | Executable literature claim | Reproduction class |
| --- | --- | --- |
| `fm_antiskyrmion_sot_full` | Normalized rigid-texture Thiele residual | `exact_normalized` |
| `fm_meron_topology_full` | `N = p w / 2` under meron boundaries | `boundary_conditioned_exact` |
| `fm_bimeron_topology_full` | Additive vortex-antivortex pair charge | `boundary_conditioned_exact` |
| `fm_vortex_topology_full` | Contour winding and `q = n p / 2` core charge | `exact_coefficient`; `boundary_conditioned_exact` |

Structural DMI or topology alignment is recorded separately as
`structural_alignment`. It cannot promote project-specific coefficients to an
exact literature reproduction.

## Primary equation anchors

- B4 uses Hanke et al., Phys. Rev. B 101, 014428 (2020), Eqs. (1)-(4),
  printed page 2, for the normalized Thiele equation, topology, dissipation,
  and generalized force. Hoffmann et al., Nature Communications 8, 308
  (2017), Eqs. (5) and (7), printed pages 2 and 5, supports only the
  anisotropic-DMI route family.
- C2 uses Gao et al., Nature Communications 10, 5603 (2019), Eq. (1) and
  `N = p w / 2`, printed page 2. Augustin et al., Nature Communications 12,
  185 (2021), Eq. (4), printed page 3, provides a second density anchor.
- C3 uses Gao et al., Eq. (2), printed page 2, for the pair-charge transform.
  Goebel et al., Phys. Rev. B 99, 060407(R) (2019), Eq. (1), printed page
  060407-2, supports the integer magnetic-bimeron topology structurally.
- C4 uses Hoffmann et al., Eq. (4), printed page 2, for closed-contour winding,
  and Tretiakov and Tchernyshyov, Phys. Rev. B 75, 012408 (2007), printed page
  1, for the separate `q = n p / 2` polarized-core charge.

Each source expression is stored as normalized ASCII together with a SHA-256
digest. A DOI or paper title without an equation/page locator is insufficient.

## Executable transform contract

An exact claim must register four distinct Wolfram result keys:

1. the cited source expression;
2. the expression after declared symbol and convention transformations;
3. the project target expression;
4. a Boolean equivalence regression.

The record must also preserve symbol mappings, orientation/sign conventions,
boundary conditions, uncovered terms, and project extensions. Capability
registry loading re-evaluates these assertions against a completed generated
record. Merely registering a YAML path cannot create a passed badge.

## Reproduction commands

```bash
python -m spintexture_agent.cli evidence \
  --cards evidence_cards/extended \
  --out analysis/evidence_runs/extended_literature_01 \
  --wolfram-timeout 300

python -m spintexture_agent.cli machine-audit \
  --specs machine_audit_specs/extended \
  --evidence-runs analysis/evidence_runs/extended_literature_01 \
  --out analysis/machine_audit/extended_literature_01

python -m spintexture_agent.cli assertion-coverage \
  --evidence-runs \
    analysis/evidence_runs/core3_latest \
    analysis/evidence_runs/extended_literature_01 \
  --out analysis/assertion_coverage/literature_02 \
  --require-complete
```

## Verified outcome

- Evidence execution: 4/4 routes, 56/56 declared comparisons passed.
- Machine audit: 4/4 formal routes passed; every material-applicability audit
  remains incomplete; suite status is `conditional_pass`.
- Assertion coverage: 7/7 full routes and 204/204 registered result keys passed.
- Capability registry: all seven full routes have executable
  `literature_reproduction=passed` evidence.

The outcome supports equation-bounded formal-route claims. It does not establish
the DMI tensor, SOT response, boundary conditions, or empirical adequacy of any
named material.

## Source links

- Hoffmann et al.: https://www.nature.com/articles/s41467-017-00313-0
- Hanke et al.: https://arxiv.org/abs/1911.01987
- Gao et al.: https://www.nature.com/articles/s41467-019-13642-z
- Augustin et al.: https://www.nature.com/articles/s41467-020-20497-2
- Goebel et al.: https://doi.org/10.1103/PhysRevB.99.060407
- Tretiakov and Tchernyshyov: https://arxiv.org/abs/cond-mat/0611392
